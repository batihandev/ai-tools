#!/usr/bin/env python3
"""
screen_explain — analyze recent screenshots with a local VLM (Ollama) and cache results.

USAGE
  # 1) Latest screenshot from SCREENSHOT_DIR
  screen_explain

  # 2) Latest N screenshots from SCREENSHOT_DIR
  screen_explain 3

  # 3) Force a new run (bypass cache)
  screen_explain new
  screen_explain 3 new

  # 4) Analyze a specific file
  screen_explain /path/to/image.png
  screen_explain path /path/to/image.png

  # 5) Analyze a directory (latest N from that directory)
  screen_explain /path/to/folder 5
  screen_explain /path/to/folder 5 new

  # 6) Override model
  screen_explain --model qwen2.5vl:3b
  screen_explain 3 --model qwen2.5vl:3b
  screen_explain /path/to/image.png --model qwen2.5vl:3b

NOTES
  - Requires env var SCREENSHOT_DIR for default mode.
  - Cache:
      logs/vlm-cache/index.json maps "fast key" -> "content key"
      logs/vlm-cache/<content-key>.json or .txt stores the actual result
  - Mirror:
      logs/vlm-mirror stores copies of inputs to avoid slow reads from /mnt/c (WSL/Windows FS).
      Retention: last 20 files and <= 100 MB total (oldest pruned).
  - Errors are NOT cached (only written to logs/screen_explain-last.json and stderr).
"""
from __future__ import annotations

import hashlib
import heapq
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Any, Optional, Tuple

from .helper.env import load_repo_dotenv
from .helper.spinner import with_spinner
from .helper.vlm import ollama_chat_with_images
from .helper.colors import Colors


load_repo_dotenv()

BASE_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

CACHE_DIR = LOG_DIR / "vlm-cache"
CACHE_DIR.mkdir(exist_ok=True)

CACHE_INDEX = CACHE_DIR / "index.json"  # fast-key -> content-key
LAST_JSON = LOG_DIR / "screen_explain-last.json"

MIRROR_DIR = LOG_DIR / "vlm-mirror"
MIRROR_DIR.mkdir(exist_ok=True)

# Retention policy
MIRROR_MAX_FILES = 20
MIRROR_MAX_BYTES = 100 * 1024 * 1024  # 100 MB

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

_JSON_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*\n(.*?)\n\s*```\s*$",
    re.DOTALL | re.IGNORECASE,
)


@dataclass(frozen=True)
class Args:
    target: str | None
    count: int | None
    model: str | None
    force_new: bool
    quality: bool


def parse_args(argv: list[str]) -> Args:
    if any(a in ("-h", "--help", "help") for a in argv):
        print(__doc__.strip())
        sys.exit(0)

    target: Optional[str] = None
    count: Optional[int] = None
    model: Optional[str] = None
    force_new = False
    quality = False

    tokens = list(argv)
    if tokens and tokens[0] == "path":
        tokens = tokens[1:]

    it = iter(tokens)
    for a in it:
        if a == "--model":
            model = next(it, None)
            continue
        if a == "new":
            force_new = True
            continue
        if a == "quality":
            quality = True
            continue
        if target is None:
            target = a
            continue
        if count is None and a.isdigit():
            count = int(a)
            continue
        print(f"{Colors.c('[screen_explain]')} {Colors.r(f'Unexpected arg: {a}')}", file=sys.stderr)
        sys.exit(1)

    if target and target.isdigit() and count is None:
        count = int(target)
        target = None

    return Args(target=target, count=count, model=model, force_new=force_new, quality=quality)


def screenshot_dir() -> Path:
    p = os.getenv("SCREENSHOT_DIR")
    if not p:
        print(f"{Colors.c('[screen_explain]')} {Colors.r('SCREENSHOT_DIR environment variable is not set.')}", file=sys.stderr)
        sys.exit(1)
    d = Path(p)
    if not d.exists():
        print(f"{Colors.c('[screen_explain]')} {Colors.r(f'Directory {d} does not exist.')}", file=sys.stderr)
        sys.exit(1)
    return d


def pick_images(folder: Path, n: int) -> list[Path]:
    entries: list[tuple[int, Path]] = []
    try:
        with os.scandir(folder) as it:
            for e in it:
                if not e.is_file():
                    continue
                ext = Path(e.name).suffix.lower()
                if ext not in IMAGE_EXTS:
                    continue
                st = e.stat()
                entries.append((st.st_mtime_ns, Path(e.path)))
    except FileNotFoundError:
        return []

    top = heapq.nlargest(n, entries, key=lambda t: t[0])
    return [p for _mt, p in top]


def build_prompt(n: int) -> str:
    return (
        dedent(
            f"""
        You are a precise screenshot/UI analyst for developers.

        Rules:
        - Describe what is visible on screen.
        - Identify errors or anomalies.
        - Suggest concrete next checks.
        - Return STRICT JSON only.
        - No markdown. No explanations.

        Analyze {n} screenshot(s).

        {{
          "context": "...",
          "detected_text": [],
          "ui_elements": [],
          "issues": [],
          "hypotheses": [],
          "next_checks": [],
          "uncertainties": []
        }}
        """
        )
        .strip()
    )


def _sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _strip_json_fence(s: str) -> str:
    m = _JSON_FENCE_RE.match(s)
    if not m:
        return s.strip()
    return m.group(1).strip()


def _try_parse_json(maybe: Any) -> tuple[Optional[Any], Optional[str]]:
    if isinstance(maybe, (dict, list, int, float, bool)) or maybe is None:
        return maybe, None

    if not isinstance(maybe, str):
        return None, str(maybe)

    raw = maybe
    s = _strip_json_fence(raw)

    try:
        parsed = json.loads(s)
    except Exception:
        return None, raw

    if isinstance(parsed, str):
        s2 = _strip_json_fence(parsed).strip()
        if (s2.startswith("{") and s2.endswith("}")) or (s2.startswith("[") and s2.endswith("]")):
            try:
                parsed2 = json.loads(s2)
                return parsed2, raw
            except Exception:
                return parsed, raw

    return parsed, raw


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _read_index() -> dict[str, str]:
    try:
        if CACHE_INDEX.exists():
            obj = json.loads(CACHE_INDEX.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                return {str(k): str(v) for k, v in obj.items()}
    except Exception as e:
        print(f"{Colors.c('[screen_explain]')} {Colors.r(f'Error reading cache index: {e}')}", file=sys.stderr)
    return {}


def _write_index(idx: dict[str, str]) -> None:
    _atomic_write_text(CACHE_INDEX, json.dumps(idx, indent=2, ensure_ascii=False))


def _fast_sig_for_file(p: Path) -> str:
    st = p.stat()
    return f"{p.name}|{st.st_size}|{st.st_mtime_ns}"


def _fast_key(imgs: list[Path], prompt: str, model: str | None) -> str:
    model_s = model or "default"
    sigs = "\n".join(_fast_sig_for_file(p) for p in imgs)
    material = f"model:{model_s}\nfiles:\n{sigs}\nprompt:{prompt}".encode("utf-8")
    return _sha256_bytes(material)


def _content_hash_images(imgs: list[Path]) -> str:
    h = hashlib.sha256()
    for p in imgs:
        st = p.stat()
        h.update(f"{p.name}|{st.st_size}|{st.st_mtime_ns}\n".encode("utf-8"))
    return h.hexdigest()


def _content_key(imgs: list[Path], prompt: str, model: str | None) -> str:
    img_hash = _content_hash_images(imgs)
    model_s = model or "default"
    material = f"model:{model_s}\nimages:{img_hash}\nprompt:{prompt}".encode("utf-8")
    return _sha256_bytes(material)


def _cache_paths(content_key: str) -> tuple[Path, Path]:
    return (CACHE_DIR / f"{content_key}.json", CACHE_DIR / f"{content_key}.txt")


def _read_cached(ck: str) -> Optional[str]:
    cache_json_path, cache_txt_path = _cache_paths(ck)
    if cache_json_path.exists():
        cached = json.loads(cache_json_path.read_text(encoding="utf-8"))
        return json.dumps(cached, indent=2, ensure_ascii=False)
    if cache_txt_path.exists():
        return cache_txt_path.read_text(encoding="utf-8")
    return None


def _write_cache(ck: str, text: str, is_json: bool) -> None:
    cache_json_path, cache_txt_path = _cache_paths(ck)
    if is_json:
        _atomic_write_text(cache_json_path, text)
    else:
        _atomic_write_text(cache_txt_path, text)


def _mirror_name_for(src: Path, idx: int) -> str:
    st = src.stat()
    safe_stem = src.stem.replace(" ", "_")
    return f"{idx:02d}__{safe_stem}__{st.st_size}__{st.st_mtime_ns}{src.suffix.lower()}"


def _mirror_paths_for(srcs: list[Path]) -> list[Path]:
    return [MIRROR_DIR / _mirror_name_for(p, i) for i, p in enumerate(srcs)]


def _ensure_mirrored(srcs: list[Path]) -> list[Path]:
    dsts = _mirror_paths_for(srcs)
    for src, dst in zip(srcs, dsts):
        if dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    return dsts


def _prune_mirror_dir(max_files: int, max_bytes: int) -> None:
    files: list[Tuple[Path, int, float]] = []
    total = 0

    for p in MIRROR_DIR.iterdir():
        try:
            if not p.is_file():
                continue
            st = p.stat()
            files.append((p, st.st_size, st.st_mtime))
            total += st.st_size
        except Exception as e:
            print(f"{Colors.c('[screen_explain]')} {Colors.r(f'Error processing mirror file {p}: {e}')}", file=sys.stderr)

    files.sort(key=lambda t: t[2])  # oldest first

    def _delete_one(pp: Path, sz: int) -> None:
        nonlocal total
        try:
            pp.unlink()
            total -= sz
        except Exception as e:
            print(f"{Colors.c('[screen_explain]')} {Colors.r(f'Error deleting file {pp}: {e}')}", file=sys.stderr)

    while len(files) > max_files:
        p, sz, _mt = files.pop(0)
        _delete_one(p, sz)

    # Size pruning
    files = []
    total = 0
    for p in MIRROR_DIR.iterdir():
        try:
            if p.is_file():
                st = p.stat()
                files.append((p, st.st_size, st.st_mtime))
                total += st.st_size
        except Exception as e:
            print(f"{Colors.c('[screen_explain]')} {Colors.r(f'Error processing mirror file {p}: {e}')}", file=sys.stderr)
    files.sort(key=lambda t: t[2])

    while total > max_bytes and files:
        p, sz, _mt = files.pop(0)
        _delete_one(p, sz)


def main() -> None:
    args = parse_args(sys.argv[1:])
    base = screenshot_dir()

    if args.target is None:
        src_imgs = pick_images(base, args.count or 1)
    else:
        p = Path(args.target)
        if p.is_dir():
            src_imgs = pick_images(p, args.count or 5)
        else:
            src_imgs = [p]

    if not src_imgs:
        print(f"{Colors.c('[screen_explain]')} {Colors.r('No images found')}", file=sys.stderr)
        sys.exit(1)

    print(f"{Colors.c('[screen_explain]')} Using {Colors.g(str(len(src_imgs)))} image(s)")
    for p in src_imgs:
        print(f"{Colors.c('[screen_explain]')}   - {p}")

    prompt = build_prompt(len(src_imgs))

    # -------------------------
    # 1) FAST CACHE CHECK FIRST (no reads)
    # -------------------------
    if not args.force_new:
        idx = _read_index()
        fk = _fast_key(src_imgs, prompt, args.model)
        ck = idx.get(fk)
        if ck:
            cached_text = _read_cached(ck)
            if cached_text is not None:
                _atomic_write_text(LAST_JSON, cached_text)
                print(cached_text)
                return

    # -------------------------
    # 2) Cache miss: mirror inputs (copy only if missing)
    # -------------------------
    try:
        imgs = _ensure_mirrored(src_imgs)
        _prune_mirror_dir(MIRROR_MAX_FILES, MIRROR_MAX_BYTES)
    except Exception as e:
        print(f"{Colors.c('[screen_explain]')} {Colors.r(f'Error during mirroring: {e}')}", file=sys.stderr)
        sys.exit(1)

    # -------------------------
    # 3) Content-key caching (fast now because mirrored)
    # -------------------------
    idx = _read_index()
    fk = _fast_key(src_imgs, prompt, args.model)  # original files metadata
    ck = _content_key(imgs, prompt, args.model)   # mirrored metadata signature
    idx[fk] = ck
    _write_index(idx)

    if not args.force_new:
        cached_text = _read_cached(ck)
        if cached_text is not None:
            _atomic_write_text(LAST_JSON, cached_text)
            print(cached_text)
            return

    def _call():
        return ollama_chat_with_images(
            user_prompt=prompt,
            image_paths=imgs,
            model=args.model,
            quality_mode=args.quality,
        )

    try:
        result = with_spinner(Colors.c("screen_explain"), _call)
    except Exception as e:
        err = f"{Colors.c('[screen_explain]')} {Colors.r(f'Error during analysis: {e}')}"
        _atomic_write_text(LAST_JSON, err)
        print(err, file=sys.stderr)
        sys.exit(1)

    parsed, raw = _try_parse_json(result)

    if parsed is not None:
        out_text = json.dumps(parsed, indent=2, ensure_ascii=False)
        _write_cache(ck, out_text, is_json=True)
        _atomic_write_text(LAST_JSON, out_text)
        print(out_text)
        return

    raw_text = raw if raw is not None else str(result)
    _write_cache(ck, raw_text, is_json=False)
    _atomic_write_text(LAST_JSON, raw_text)
    print(raw_text)


if __name__ == "__main__":
    main()
