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

  # 7) Override context window
  screen_explain --ctx 8192

NOTES
  - Requires env var SCREENSHOT_DIR for default mode.
  - Caches results to logs/vlm-cache/ to avoid re-running slow vision models.
  - Mirrors images to logs/vlm-mirror/ for faster access from WSL/containers.
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
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field

from .helper.env import load_repo_dotenv
from .helper.spinner import with_spinner
from .helper.vlm import ollama_chat_with_images
from .helper.colors import Colors
from .helper.json_utils import safe_parse_model
from .helper.utils import atomic_write_text

load_repo_dotenv()

# -----------------------------------------------------------------------------
# Configuration & Constants
# -----------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

CACHE_DIR = LOG_DIR / "vlm-cache"
CACHE_DIR.mkdir(exist_ok=True)
CACHE_INDEX = CACHE_DIR / "index.json"

MIRROR_DIR = LOG_DIR / "vlm-mirror"
MIRROR_DIR.mkdir(exist_ok=True)

LAST_JSON = LOG_DIR / "screen_explain-last.json"

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

MIRROR_MAX_FILES = 20
MIRROR_MAX_BYTES = 100 * 1024 * 1024  # 100 MB


@dataclass(frozen=True)
class Args:
    target: str | None
    count: int | None
    model: str | None
    force_new: bool
    quality: bool
    ctx: int | None


# -----------------------------------------------------------------------------
# Data Models (Pydantic)
# -----------------------------------------------------------------------------

class UIElement(BaseModel):
    name: str
    description: str
    status: str = "visible"

class Issue(BaseModel):
    title: str
    severity: str = "medium"  # low, medium, high, critical
    description: str
    recommendation: str

class ScreenAnalysis(BaseModel):
    summary: str = Field(..., description="High-level summary of what is visible on the screen.")
    ui_elements: List[UIElement] = Field(default_factory=list, description="List of key UI components identified.")
    detected_text: List[str] = Field(default_factory=list, description="Important text detected on screen.")
    issues: List[Issue] = Field(default_factory=list, description="Potential errors, bugs, or anomalies found.")
    next_checks: List[str] = Field(default_factory=list, description="Suggested next steps for the developer.")
    
    # Fallback fields for raw output if parsing partially fails
    raw_output: str = ""
    is_raw_error: bool = False


# -----------------------------------------------------------------------------
# Argument Parsing
# -----------------------------------------------------------------------------

def parse_args(argv: list[str]) -> Args:
    if any(a in ("-h", "--help", "help") for a in argv):
        print(__doc__.strip())
        sys.exit(0)

    target: Optional[str] = None
    count: Optional[int] = None
    model: Optional[str] = None
    ctx: Optional[int] = None
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
        if a == "--ctx":
            val = next(it, None)
            if val and val.isdigit():
                ctx = int(val)
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

    return Args(target=target, count=count, model=model, force_new=force_new, quality=quality, ctx=ctx)


# -----------------------------------------------------------------------------
# File System & Mirroring
# -----------------------------------------------------------------------------

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


def _mirror_name_for(src: Path, idx: int) -> str:
    st = src.stat()
    safe_stem = src.stem.replace(" ", "_")
    return f"{idx:02d}__{safe_stem}__{st.st_size}__{st.st_mtime_ns}{src.suffix.lower()}"


def _ensure_mirrored(srcs: list[Path]) -> list[Path]:
    dsts = []
    for i, src in enumerate(srcs):
        dst = MIRROR_DIR / _mirror_name_for(src, i)
        dsts.append(dst)
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    return dsts


def _prune_mirror_dir(max_files: int, max_bytes: int) -> None:
    files: list[Tuple[Path, int, float]] = []
    total = 0

    for p in MIRROR_DIR.iterdir():
        if p.is_file():
            st = p.stat()
            files.append((p, st.st_size, st.st_mtime))
            total += st.st_size
    
    files.sort(key=lambda t: t[2])  # oldest first

    while len(files) > max_files:
        p, sz, _ = files.pop(0)
        p.unlink(missing_ok=True)
        total -= sz

    while total > max_bytes and files:
        p, sz, _ = files.pop(0)
        p.unlink(missing_ok=True)
        total -= sz


# -----------------------------------------------------------------------------
# Caching Logic
# -----------------------------------------------------------------------------

def _read_index() -> dict[str, str]:
    if CACHE_INDEX.exists():
        try:
            val = json.loads(CACHE_INDEX.read_text(encoding="utf-8"))
            if isinstance(val, dict):
                return val
        except Exception:
            pass
    return {}


def _write_index(idx: dict[str, str]) -> None:
    atomic_write_text(CACHE_INDEX, json.dumps(idx, indent=2))


def _fast_key(imgs: list[Path], prompt: str, model_sig: str) -> str:
    # Key based on filename + mtime + size (fast, no content read)
    sig_parts = []
    for p in imgs:
        st = p.stat()
        sig_parts.append(f"{p.name}|{st.st_size}|{st.st_mtime_ns}")
    
    material = f"model:{model_sig}\nfiles:{','.join(sig_parts)}\nprompt:{prompt}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _content_key(imgs: list[Path], prompt: str, model_sig: str) -> str:
    # Key based on actual content hash (if needed) but here matching logic:
    # We surely need to rely on the file stats being stable for local files.
    # The 'mirror' logic already ensures unique names for content.
    # So we can reuse the same logic or actually hash content if we want 100% safety.
    # For speed, we will assume mirrored filenames (including size/mtime) are sufficient.
    
    # We will just hash the filenames in the mirror, which contain metadata.
    return _fast_key(imgs, prompt, model_sig)


def _cache_paths(ck: str) -> Tuple[Path, Path]:
    return (CACHE_DIR / f"{ck}.json", CACHE_DIR / f"{ck}.txt")


# -----------------------------------------------------------------------------
# LLM & Prompting
# -----------------------------------------------------------------------------

def build_prompt(n: int) -> str:
    return dedent(f"""
        You are an expert UI/UX developer and QA engineer.
        
        Analyze the provided {n} screenshot(s).
        
        Your Goal:
        1. Summarize what is shown.
        2. Identify specific UI elements.
        3. Detect any errors, visual glitches, or weird states.
        4. Suggest what a developer should check next.

        Constraint:
        - Return ONLY valid JSON matching this schema:
        
        {{
            "summary": "string",
            "ui_elements": [
                {{ "name": "string", "description": "string", "status": "visible|hidden|disabled" }}
            ],
            "detected_text": ["string"],
            "issues": [
                {{ "title": "string", "severity": "low|medium|high|critical", "description": "string", "recommendation": "string" }}
            ],
            "next_checks": ["string"]
        }}
    """).strip()


def _make_fallback_analysis(raw: str) -> ScreenAnalysis:
    """Create fallback ScreenAnalysis when parsing fails."""
    return ScreenAnalysis(
        summary="Raw output (parsing failed)",
        raw_output=raw,
        is_raw_error=True
    )


def _format_cli(analysis: ScreenAnalysis) -> str:
    if analysis.is_raw_error:
        return f"{Colors.r('✗ Failed to parse JSON response.')}\n\nRAW OUTPUT:\n{analysis.raw_output}"

    out = []
    
    # Summary
    out.append(f"\n{Colors.b('► Summary')}")
    out.append(f"  {analysis.summary}")

    # Issues (High Priority)
    if analysis.issues:
        out.append(f"\n{Colors.r('► detected Issues')}")
        for err in analysis.issues:
            sev_color = Colors.r if err.severity in ('high', 'critical') else Colors.y
            out.append(f"  {sev_color('•')} {Colors.bold(err.title)} {Colors.grey(f'[{err.severity}]')}")
            out.append(f"    {err.description}")
            if err.recommendation:
                out.append(f"    {Colors.g('→')} {Colors.grey('Suggest:')} {err.recommendation}")

    # UI Elements (if verbose or interesting? Just listing them)
    if analysis.ui_elements:
        out.append(f"\n{Colors.c('► UI Elements')}")
        for el in analysis.ui_elements:
            out.append(f"  {Colors.c('•')} {Colors.bold(el.name)}: {el.description}")

    # Next Checks
    if analysis.next_checks:
        out.append(f"\n{Colors.g('► Next Checks')}")
        for check in analysis.next_checks:
            out.append(f"  {Colors.g('✓')} {check}")

    return "\n".join(out)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main() -> None:
    args = parse_args(sys.argv[1:])
    base = screenshot_dir()

    # Select Images
    if args.target:
        p = Path(args.target)
        if p.is_dir():
            src_imgs = pick_images(p, args.count or 5)
        else:
            src_imgs = [p]
    else:
        src_imgs = pick_images(base, args.count or 1)

    if not src_imgs:
        print(f"{Colors.c('[screen_explain]')} {Colors.r('No images found')}", file=sys.stderr)
        sys.exit(1)

    print(f"{Colors.c('[screen_explain]')} Analyzing {Colors.g(str(len(src_imgs)))} image(s)...")
    for p in src_imgs:
        print(f"  {Colors.grey(str(p))}")

    # Prepare logic
    prompt = build_prompt(len(src_imgs))
    
    # Resolve model: CLI arg > SCREEN_EXPLAIN_MODEL > None (falls back to global default in VLM)
    model_to_use = args.model or os.getenv("SCREEN_EXPLAIN_MODEL")
    if model_to_use and not model_to_use.strip():
        model_to_use = None
        
    model_sig = model_to_use or "default"
    if args.ctx:
        model_sig += f"|ctx={args.ctx}"

    # Index Check (Fast)
    idx = _read_index()
    fk = _fast_key(src_imgs, prompt, model_sig)
    
    if not args.force_new:
        ck = idx.get(fk)
        if ck:
            json_path, _ = _cache_paths(ck)
            if json_path.exists():
                try:
                    cached_data = json.loads(json_path.read_text())
                    # Validate against current schema
                    analysis = ScreenAnalysis(**cached_data)
                    print(_format_cli(analysis))
                    return
                except Exception:
                    pass  # Cache invalid or schema changed

    # Mirror Images (IO)
    try:
        mirrored_imgs = _ensure_mirrored(src_imgs)
        _prune_mirror_dir(MIRROR_MAX_FILES, MIRROR_MAX_BYTES)
    except Exception as e:
        print(f"{Colors.r('Error mirroring images:')} {e}", file=sys.stderr)
        sys.exit(1)

    # Content Key
    ck = _content_key(mirrored_imgs, prompt, model_sig)
    
    # Run Inference
    def _run() -> str:
        return ollama_chat_with_images(
            user_prompt=prompt,
            image_paths=mirrored_imgs,
            model=model_to_use,
            num_ctx=args.ctx,
            quality_mode=args.quality,
        )

    try:
        raw_res = with_spinner(Colors.c("screen_explain thinking..."), _run)
    except Exception as e:
        print(f"\n{Colors.r('Analysis failed:')} {e}", file=sys.stderr)
        sys.exit(1)

    # Parse & Cache
    analysis = safe_parse_model(raw_res, ScreenAnalysis, _make_fallback_analysis)
    
    # Save to cache
    json_path, _ = _cache_paths(ck)
    try:
        atomic_write_text(json_path, analysis.model_dump_json())
        idx[fk] = ck
        _write_index(idx)
        atomic_write_text(LAST_JSON, analysis.model_dump_json(indent=2))
    except Exception as e:
        print(f"{Colors.y('Warning: could not write cache:')} {e}", file=sys.stderr)

    # Display
    print(_format_cli(analysis))


if __name__ == "__main__":
    main()
