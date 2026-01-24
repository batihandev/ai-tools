# scripts/helper/vlm.py
from __future__ import annotations

import base64
import io
import os
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple

import requests
from PIL import Image

from .ollama_utils import resolve_ollama_url

BASE_DIR = Path(__file__).resolve().parents[2]
LOG_DIR = BASE_DIR / "logs"

# ============================================================
# One-toggle debug
# ============================================================
# VLM_DEBUG=1 enables verbose logging (no base64 printed).
#
# Behavior goals:
# - Prefer /api/chat ONLY (no /api/generate)
# - Resize strategy (scale, not JPEG quality):
#     * normal mode: start at 60%, on retriable error decrease by 10% per retry
#         - max 3 retries => attempts: 60%, 50%, 40%, 30%
#     * quality mode: start at 90%, retry once at 75%
# - Snap resized dimensions down to a stable multiple (default: 32)
# - Auto num_ctx based on (resized) image dimensions:
#     * < 1000x1000  -> 4096
#     * < 2000x2000  -> 8192
#     * else         -> 12288
# - In debug mode, save the exact JPEG payload sent per attempt into logs/vlm-images
# - Optional: set num_batch to reduce peak memory pressure / fragmentation risk
#
# Optional env overrides:
# - DEFAULT_VLM_MODEL      (default env: qwen2.5vl:7b)
# - VLM_TIMEOUT            (default: 180)
#
# Encoding env:
# - VLM_JPEG_QUALITY       (default: 85)
#
# Dimension snapping env:
# - VLM_SNAP_MULT          (default: 32)
# - VLM_SNAP_MIN           (default: 64)
#
# Batch env:
# - VLM_NUM_BATCH          (default: 128)        # sent as options.num_batch (if > 0)
#
# Verbosity / UI:
# - VLM_VERBOSE            (default: 1)
# - VLM_QUIET              (default: 0)
# - VLM_USE_RICH           (default: 1)
# ============================================================

DEFAULT_JPEG_QUALITY = 85
DEFAULT_SNAP_MULT = 32
DEFAULT_SNAP_MIN = 64
DEFAULT_SNAP_MULT = 32
DEFAULT_SNAP_MIN = 64
DEFAULT_NUM_BATCH = 128
DEFAULT_MAX_CTX = 8192  # Cap auto-context to prevent OOM on typical GPUs


# -----------------------------
# Model config
# -----------------------------

def get_default_vlm_model() -> str:
    return os.getenv("DEFAULT_VLM_MODEL", "qwen2.5vl:3b")


# -----------------------------
# Env helpers
# -----------------------------

def _env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip() == "1"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def _safe_preview(s: str, limit: int = 300) -> str:
    s = s.replace("\r\n", "\n")
    return s if len(s) <= limit else s[:limit] + "..."


# -----------------------------
# Logging / UI helpers
# -----------------------------

def _wants_verbose() -> bool:
    if _env_bool("VLM_QUIET", "0"):
        return False
    return _env_bool("VLM_VERBOSE", "1")


def _wants_rich() -> bool:
    return _env_bool("VLM_USE_RICH", "1")


class _UI:
    def __init__(self, debug: bool):
        self.debug = debug
        self.verbose = _wants_verbose() or debug
        self._use_rich = _wants_rich()
        self._console = None
        self._Spinner = None

        if self._use_rich:
            try:
                from rich.console import Console  # type: ignore
                from rich.status import Status  # type: ignore
                self._console = Console()
                self._Spinner = Status
            except Exception:
                self._console = None
                self._Spinner = None

    def log(self, msg: str) -> None:
        if not self.verbose:
            return
        if self._console is not None:
            self._console.print(msg)
        else:
            print(msg)

    def warn(self, msg: str) -> None:
        if self._console is not None:
            self._console.print(f"[yellow]{msg}[/yellow]")
        else:
            print(msg)

    def err(self, msg: str) -> None:
        if self._console is not None:
            self._console.print(f"[red]{msg}[/red]")
        else:
            print(msg)

    def status(self, msg: str):
        if self._Spinner is not None and self._console is not None:
            return self._Spinner(msg, console=self._console)
        return _PlainStatus(self, msg)


class _PlainStatus:
    def __init__(self, ui: _UI, msg: str):
        self.ui = ui
        self.msg = msg

    def __enter__(self):
        self.ui.log(self.msg)
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


# -----------------------------
# Image helpers
# -----------------------------

def _encode_jpeg_bytes(im: Image.Image, quality: int) -> bytes:
    q = max(30, min(95, int(quality)))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=q, optimize=True, progressive=True, subsampling=0)
    return buf.getvalue()


def _encode_jpeg_b64(im: Image.Image, quality: int) -> str:
    return base64.b64encode(_encode_jpeg_bytes(im, quality)).decode("utf-8")


def _debug_dir() -> Path:
    d = Path(__file__).resolve().parents[2] / "logs" / "vlm-images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_debug_jpeg(panel: Image.Image, out_path: Path, quality: int) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(_encode_jpeg_bytes(panel, quality))


def _snap_size(w: int, h: int, *, snap_mult: int, snap_min: int) -> Tuple[int, int]:
    """
    Snap down to a multiple to avoid "bad" sizes that can trigger backend tiling/assert paths.
    Never upscale due to snapping (caller clamps to pre-snap size).
    """
    snap_mult = max(1, int(snap_mult))
    snap_min = max(1, int(snap_min))

    def _snap_one(x: int) -> int:
        x = int(x)
        if x <= snap_min:
            return snap_min
        return max(snap_min, (x // snap_mult) * snap_mult)

    sw = max(1, _snap_one(w))
    sh = max(1, _snap_one(h))
    return sw, sh


def _resize_percent_and_snap(im: Image.Image, scale: float, *, snap_mult: int, snap_min: int) -> Image.Image:
    """
    Resize to a percentage of original size (always downscale; never upscale),
    then snap down to stable multiples (never upscale due to snapping).
    """
    w, h = im.size
    if w <= 0 or h <= 0:
        return im

    s = float(scale)
    s = max(0.01, min(1.0, s))

    rw = max(1, int(w * s))
    rh = max(1, int(h * s))

    # First resize (or keep size if identical)
    if (rw, rh) == (w, h):
        resized = im
    else:
        resized = im.resize((rw, rh), Image.LANCZOS)

    # Snap after resize, but never upscale
    sw, sh = _snap_size(resized.size[0], resized.size[1], snap_mult=snap_mult, snap_min=snap_min)
    sw = min(sw, resized.size[0])
    sh = min(sh, resized.size[1])
    sw = max(1, sw)
    sh = max(1, sh)

    if (sw, sh) == resized.size:
        return resized
    return resized.resize((sw, sh), Image.LANCZOS)


def _prepare_images_for_vlm(
    paths: List[Path],
    *,
    scale: float,
    debug_save_prefix: Optional[str],
    jpeg_quality: int,
    snap_mult: int,
    snap_min: int,
) -> Tuple[List[str], List[Tuple[int, int]]]:
    debug_dir = _debug_dir() if debug_save_prefix is not None else None

    images_b64: List[str] = []
    sizes: List[Tuple[int, int]] = []

    for idx, p in enumerate(paths):
        with Image.open(p) as im0:
            im0 = im0.convert("RGB")
            panel = _resize_percent_and_snap(im0, scale, snap_mult=snap_mult, snap_min=snap_min)

        w, h = panel.size
        sizes.append((w, h))

        if debug_dir is not None:
            _save_debug_jpeg(
                panel,
                debug_dir / f"{debug_save_prefix}__{p.stem}__i{idx}__{w}x{h}.jpg",
                quality=jpeg_quality,
            )

        images_b64.append(_encode_jpeg_b64(panel, quality=jpeg_quality))

    return images_b64, sizes


# -----------------------------
# VLM heuristics
# -----------------------------

def _looks_like_template_leak(content: str) -> bool:
    c = content.strip()
    if not c:
        return False
    markers = (
        "<|im_start|>",
        "<|im_end|>",
        "<|assistant|>",
        "<|user|>",
        "<|system|>",
    )
    return any(m in c for m in markers)


def _pick_num_ctx_from_sizes(sizes: List[Tuple[int, int]]) -> int:
    if not sizes:
        return 4096

    max_w = max(w for w, _ in sizes)
    max_h = max(h for _, h in sizes)
    
    # Allow env override for the ceiling
    max_ctx = _env_int("VLM_MAX_CTX", DEFAULT_MAX_CTX)

    if max_w < 1000 and max_h < 1000:
        return 4096
    
    # If not small, jump to 8192 (or capped max)
    # 12288 was often overkill and caused failures on 8GB VRAM cards
    return min(8192, max_ctx)


def _probe_ollama(base_url: str) -> str:
    try:
        r = requests.get(f"{base_url}/api/version", timeout=5)
        r.raise_for_status()
        return r.text.strip()
    except Exception as e:
        return f"ERROR: {e}"


def _is_retriable_error(e: Exception) -> bool:
    if isinstance(e, requests.Timeout):
        return True
    if isinstance(e, requests.ConnectionError):
        return True
    if isinstance(e, requests.HTTPError) and e.response is not None:
        try:
            return int(e.response.status_code) >= 500
        except Exception:
            return False
    return False


# -----------------------------
# Ollama call (chat only, adaptive + retry by resize scale)
# -----------------------------

def ollama_chat_with_images(
    *,
    user_prompt: str,
    image_paths: list[Path],
    model: str | None = None,
    num_ctx: int | None = None,  # If None, auto-calculated. If set, respected.
    temperature: float = 0.2,
    timeout: int = 180,
    quality_mode: bool = False,  # "quality" flag: scale ladder 90% then 75%
) -> str:
    debug = _env_bool("VLM_DEBUG")
    ui = _UI(debug=debug)

    timeout = _env_int("VLM_TIMEOUT", timeout)

    base_url = resolve_ollama_url("http://localhost:11434")
    model_name = model or get_default_vlm_model()

    jpeg_quality = _env_int("VLM_JPEG_QUALITY", DEFAULT_JPEG_QUALITY)
    snap_mult = _env_int("VLM_SNAP_MULT", DEFAULT_SNAP_MULT)
    snap_min = _env_int("VLM_SNAP_MIN", DEFAULT_SNAP_MIN)

    num_batch = _env_int("VLM_NUM_BATCH", DEFAULT_NUM_BATCH)
    if num_batch <= 0:
        num_batch = 0

    ui.log(f"[vlm] model={model_name} base_url={base_url}")
    ui.log(f"[vlm] images={len(image_paths)} timeout={timeout}s temp={temperature}")
    ui.log(f"[vlm] encoding=jpeg quality={jpeg_quality} api=/api/chat only")
    ui.log(f"[vlm] snap_mult={snap_mult} snap_min={snap_min} num_batch={num_batch or 'unset'}")

    if debug:
        ui.log(f"[vlm] /api/version -> {_probe_ollama(base_url)}")

    def call_chat(images_b64: List[str], effective_num_ctx: int) -> str:
        options: dict[str, Any] = {
            "num_ctx": effective_num_ctx,
            "temperature": temperature,
        }
        if num_batch > 0:
            options["num_batch"] = num_batch

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": "Output STRICT JSON only."},
                {"role": "user", "content": user_prompt, "images": images_b64},
            ],
            "options": options,
            "stream": False,
        }

        t0 = time.time()
        with ui.status("[vlm] calling Ollama /api/chat ..."):
            r = requests.post(f"{base_url}/api/chat", json=payload, timeout=timeout)
        dt = int((time.time() - t0) * 1000)

        r.raise_for_status()
        data = r.json()
        content = data.get("message", {}).get("content", "")

        ui.log(f"[vlm] /api/chat ok ({dt}ms) done_reason={data.get('done_reason')!r}")
        if debug:
            ui.log(f"[vlm] prompt_eval_count={data.get('prompt_eval_count')!r} eval_count={data.get('eval_count')!r}")
            ui.log(f"[vlm] content_preview={_safe_preview(content, 200)!r}")

        return content if isinstance(content, str) else ""

    # Scale ladders:
    # - quality_mode: 90% then 75% (one retry)
    # - normal: 60% then -10% for 3 retries (60,50,40,30)
    if quality_mode:
        scales: List[float] = [0.90, 0.75]
    else:
        scales = [0.60, 0.50, 0.40, 0.30]

    last_err: Optional[Exception] = None

    for attempt_no, scale in enumerate(scales, start=1):
        debug_prefix = None
        if debug:
            debug_prefix = f"att{attempt_no:02d}__scale{int(scale*100):03d}"

        try:
            with ui.status(f"[vlm] preparing images (attempt {attempt_no}/{len(scales)} scale={scale:.2f})"):
                images_b64, sizes = _prepare_images_for_vlm(
                    list(image_paths),
                    scale=scale,
                    debug_save_prefix=debug_prefix,
                    jpeg_quality=jpeg_quality,
                    snap_mult=snap_mult,
                    snap_min=snap_min,
                )
        except Exception as e:
            last_err = e
            ui.err(f"[vlm] image preparation failed: {e}")
            # preparation issues: try next scale
            continue

        if num_ctx is not None and num_ctx > 0:
            effective_num_ctx = num_ctx
            ui.log(f"[vlm] attempt {attempt_no}/{len(scales)} scale={scale:.2f} using explicit num_ctx={effective_num_ctx}")
        else:
            effective_num_ctx = _pick_num_ctx_from_sizes(sizes)
            ui.log(
                f"[vlm] attempt {attempt_no}/{len(scales)} scale={scale:.2f} "
                f"imgs={len(images_b64)} sizes={sizes} => num_ctx={effective_num_ctx}"
            )

        try:
            out = call_chat(images_b64, effective_num_ctx)
        except Exception as e:
            last_err = e
            ui.warn(f"[vlm] chat failed: {type(e).__name__}: {e}")

            if _is_retriable_error(e):
                ui.warn("[vlm] retriable error; retrying with smaller resize scale ...")
                continue

            # Non-retriable: fail immediately.
            raise

        def _log_to_file(content: str, filename: Path) -> None:
            with open(filename, 'a') as f:
                f.write(content + '\n')

        # Example usage within a retry loop
        if out.strip() == "" or _looks_like_template_leak(out):
            last_err = RuntimeError(f"VLM returned unusable output: {_safe_preview(out, 200)!r}")
            ui.warn("[vlm] chat output unusable (empty/template). retrying with smaller resize scale ...")
            
            ui.err(f"[vlm] Full response: {out}")
            _log_to_file(out, LOG_DIR / "unusable_outputs.log")
            
            continue


        return out

    if last_err is None:
        raise RuntimeError("VLM failed for unknown reasons (no exception captured).")

    raise last_err
