# scripts/helper/vlm.py
from __future__ import annotations

import base64
import io
import os
import time
from pathlib import Path
from typing import Any, Optional

import requests
from PIL import Image

from .ollama_utils import resolve_ollama_url
from .ui import UI

# =============================================================================
# Paths
# =============================================================================

BASE_DIR = Path(__file__).resolve().parents[2]
LOG_DIR = BASE_DIR / "logs"

# =============================================================================
# Defaults (keep behavior stable)
# =============================================================================

DEFAULT_VLM_MODEL = "qwen2.5vl:3b"
DEFAULT_TIMEOUT_S = 180
DEFAULT_ENDPOINT = "chat"  # ("chat" | "generate")

DEFAULT_JPEG_QUALITY = 80
DEFAULT_SNAP_MULT = 32
DEFAULT_SNAP_MIN = 64

DEFAULT_NUM_BATCH = 64
DEFAULT_MAX_CTX = 8196  # hard cap for auto-context to prevent OOM on typical GPUs

# =============================================================================
# Env var names
# =============================================================================

ENV_DEBUG = "VLM_DEBUG"
ENV_TIMEOUT = "VLM_TIMEOUT"
ENV_ENDPOINT = "VLM_ENDPOINT"

ENV_MODEL = "DEFAULT_VLM_MODEL"
ENV_JPEG_QUALITY = "VLM_JPEG_QUALITY"
ENV_SNAP_MULT = "VLM_SNAP_MULT"
ENV_SNAP_MIN = "VLM_SNAP_MIN"

ENV_NUM_BATCH = "VLM_NUM_BATCH"
ENV_NUM_PREDICT = "VLM_NUM_PREDICT"
ENV_MAX_CTX = "VLM_MAX_CTX"

# =============================================================================
# Model config
# =============================================================================


def get_default_vlm_model() -> str:
    return os.getenv(ENV_MODEL, DEFAULT_VLM_MODEL)


# =============================================================================
# Env helpers
# =============================================================================


def _env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip() == "1"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def _env_str(name: str, default: str) -> str:
    v = os.getenv(name, default)
    return v.strip() if isinstance(v, str) else default


def _safe_preview(s: str, limit: int = 300) -> str:
    s = s.replace("\r\n", "\n")
    return s if len(s) <= limit else s[:limit] + "..."


# =============================================================================
# Image helpers
# =============================================================================


def _encode_jpeg_bytes(im: Image.Image, quality: int) -> bytes:
    q = max(30, min(95, int(quality)))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=q, optimize=True, progressive=True, subsampling=0)
    return buf.getvalue()


def _encode_jpeg_b64(im: Image.Image, quality: int) -> str:
    return base64.b64encode(_encode_jpeg_bytes(im, quality)).decode("utf-8")


def _debug_dir() -> Path:
    d = BASE_DIR / "logs" / "vlm-images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_debug_jpeg(panel: Image.Image, out_path: Path, quality: int) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(_encode_jpeg_bytes(panel, quality))


def _snap_size(w: int, h: int, *, snap_mult: int, snap_min: int) -> tuple[int, int]:
    """
    Snap down to stable multiples to avoid backend tiling/assert paths.
    Never upscale due to snapping.
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

    s = max(0.01, min(1.0, float(scale)))
    rw = max(1, int(w * s))
    rh = max(1, int(h * s))

    resized = im if (rw, rh) == (w, h) else im.resize((rw, rh), Image.LANCZOS)

    # Snap after resize, but never upscale
    sw, sh = _snap_size(resized.size[0], resized.size[1], snap_mult=snap_mult, snap_min=snap_min)
    sw = min(sw, resized.size[0])
    sh = min(sh, resized.size[1])
    sw = max(1, sw)
    sh = max(1, sh)

    return resized if (sw, sh) == resized.size else resized.resize((sw, sh), Image.LANCZOS)


def _prepare_images_for_vlm(
    paths: list[Path],
    *,
    scale: float,
    debug_save_prefix: Optional[str],
    jpeg_quality: int,
    snap_mult: int,
    snap_min: int,
) -> tuple[list[str], list[tuple[int, int]]]:
    debug_dir = _debug_dir() if debug_save_prefix is not None else None

    images_b64: list[str] = []
    sizes: list[tuple[int, int]] = []

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


# =============================================================================
# Output heuristics
# =============================================================================


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


# =============================================================================
# Error heuristics
# =============================================================================


def _probe_ollama(base_url: str) -> str:
    # Debug-only helper; keep lightweight.
    try:
        r = requests.get(f"{base_url}/api/version", timeout=5)
        r.raise_for_status()
        return r.text.strip()
    except Exception as e:
        return f"ERROR: {e}"


def _is_retriable_error(e: Exception) -> bool:
    if isinstance(e, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(e, requests.HTTPError) and e.response is not None:
        try:
            return int(e.response.status_code) >= 500
        except Exception:
            return False
    return False


def _looks_like_endpoint_mismatch(e: Exception) -> bool:
    """
    Heuristic for trying the other endpoint:
    - 404 (endpoint missing)
    - 400 with common schema mismatch text
    """
    if isinstance(e, requests.HTTPError) and e.response is not None:
        code = int(getattr(e.response, "status_code", 0) or 0)
        if code == 404:
            return True
        if code == 400:
            try:
                body = e.response.text or ""
            except Exception:
                body = ""
            body_l = body.lower()
            if "unknown field" in body_l or "invalid" in body_l or "messages" in body_l:
                return True
    return False


# =============================================================================
# Main entry
# =============================================================================


def ollama_chat_with_images(
    *,
    system_prompt: str,
    user_prompt: str,
    image_paths: list[Path],
    model: str | None = None,
    num_ctx: int | None = None,  # If None, auto-calculated. If set, respected.
    temperature: float = 0.7,
    top_p: float = 0.8,
    top_k: int = 20,
    min_p: float = 0.0,
    enable_thinking: bool = False,
    timeout: int = DEFAULT_TIMEOUT_S,
    quality_mode: bool = False,  # "quality" flag: scale ladder 90% then 75%
) -> str | Any:
    debug = _env_bool(ENV_DEBUG)
    ui = UI(debug=debug)

    timeout = _env_int(ENV_TIMEOUT, timeout)

    base_url = resolve_ollama_url("http://localhost:11434")
    model_name = model or get_default_vlm_model()

    endpoint_pref = _env_str(ENV_ENDPOINT, DEFAULT_ENDPOINT).lower()
    if endpoint_pref not in ("chat", "generate"):
        endpoint_pref = DEFAULT_ENDPOINT

    jpeg_quality = _env_int(ENV_JPEG_QUALITY, DEFAULT_JPEG_QUALITY)
    snap_mult = _env_int(ENV_SNAP_MULT, DEFAULT_SNAP_MULT)
    snap_min = _env_int(ENV_SNAP_MIN, DEFAULT_SNAP_MIN)

    num_batch = _env_int(ENV_NUM_BATCH, DEFAULT_NUM_BATCH)
    if num_batch <= 0:
        num_batch = 0

    max_ctx = _env_int(ENV_MAX_CTX, DEFAULT_MAX_CTX)
    if max_ctx <= 0:
        max_ctx = DEFAULT_MAX_CTX

    ui.log(f"[vlm] model={model_name} base_url={base_url} endpoint={endpoint_pref}")
    ui.log(f"[vlm] images={len(image_paths)} timeout={timeout}s temp={temperature}")
    ui.log(f"[vlm] encoding=jpeg quality={jpeg_quality}")
    ui.log(f"[vlm] snap_mult={snap_mult} snap_min={snap_min} num_batch={num_batch or 'unset'}")

    if debug:
        ui.log(f"[vlm] /api/version -> {_probe_ollama(base_url)}")

    def _build_options(effective_num_ctx: int, current_batch: int) -> dict[str, Any]:
        options: dict[str, Any] = {
            "num_ctx": effective_num_ctx,
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "min_p": min_p,
            "enable_thinking": enable_thinking,
        }

        if current_batch > 0:
            options["num_batch"] = current_batch

        num_predict = _env_int(ENV_NUM_PREDICT, 0)
        if num_predict > 0:
            options["num_predict"] = num_predict

        return options

    def call_chat(images_b64: list[str], effective_num_ctx: int, current_batch: int) -> str:
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt, "images": images_b64},
            ],
            "options": _build_options(effective_num_ctx, current_batch),
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

    def call_generate(images_b64: list[str], effective_num_ctx: int, current_batch: int) -> str:
        payload: dict[str, Any] = {
            "model": model_name,
            "system": system_prompt,
            "prompt": user_prompt,
            "options": _build_options(effective_num_ctx, current_batch),
            "stream": False,
        }
        if images_b64:
            payload["images"] = images_b64

        t0 = time.time()
        with ui.status("[vlm] calling Ollama /api/generate ..."):
            r = requests.post(f"{base_url}/api/generate", json=payload, timeout=timeout)
        dt = int((time.time() - t0) * 1000)

        r.raise_for_status()
        data = r.json()
        content = data.get("response", "")

        ui.log(f"[vlm] /api/generate ok ({dt}ms) done_reason={data.get('done_reason')!r}")
        if debug:
            ui.log(f"[vlm] prompt_eval_count={data.get('prompt_eval_count')!r} eval_count={data.get('eval_count')!r}")
            ui.log(f"[vlm] content_preview={_safe_preview(content, 200)!r}")

        return content if isinstance(content, str) else ""

    # Scale ladders (unchanged)
    scales: list[float] = [0.90, 0.75] if quality_mode else [0.60, 0.50, 0.40, 0.30]

    last_err: Optional[Exception] = None
    current_batch = 0 if num_batch <= 0 else num_batch

    def _append_unusable(out: str) -> None:
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(LOG_DIR / "unusable_outputs.log", "a", encoding="utf-8") as f:
                f.write(out + "\n")
        except Exception:
            pass

    scale_idx = 0
    while scale_idx < len(scales):
        scale = scales[scale_idx]

        debug_prefix = f"att{scale_idx+1:02d}__scale{int(scale*100):03d}" if debug else None
        attempt_label = f"s{scale_idx+1}b{current_batch if current_batch else 'Def'}"

        try:
            with ui.status(f"[vlm] preparing images ({attempt_label} scale={scale:.2f})"):
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
            scale_idx += 1
            continue

        if num_ctx is not None and num_ctx > 0:
            effective_num_ctx = num_ctx
            ui.log(f"[vlm] {attempt_label} scale={scale:.2f} using explicit num_ctx={effective_num_ctx}")
        else:
            effective_num_ctx = max_ctx
            ui.log(
                f"[vlm] {attempt_label} scale={scale:.2f} "
                f"imgs={len(images_b64)} sizes={sizes} => num_ctx={effective_num_ctx}"
            )

        # Endpoint preference + one-time fallback (unchanged)
        call_order = [("chat", call_chat), ("generate", call_generate)] if endpoint_pref == "chat" else [
            ("generate", call_generate),
            ("chat", call_chat),
        ]

        out: Optional[str] = None
        endpoint_err: Optional[Exception] = None

        for endpoint_name, fn in call_order:
            try:
                out = fn(images_b64, effective_num_ctx, current_batch)
                endpoint_err = None
                break
            except Exception as e:
                endpoint_err = e
                ui.warn(f"[vlm] {endpoint_name} failed: {type(e).__name__}: {e}")

                # Only try the other endpoint if it looks like mismatch.
                if not _looks_like_endpoint_mismatch(e):
                    break

        if endpoint_err is not None and out is None:
            last_err = endpoint_err

            if _is_retriable_error(endpoint_err):
                eff_batch = current_batch if current_batch > 0 else DEFAULT_NUM_BATCH
                if eff_batch > 16:
                    new_batch = max(16, eff_batch // 2)
                    ui.warn(f"[vlm] retriable error; reducing batch {eff_batch}->{new_batch} and retrying same scale")
                    current_batch = new_batch
                    continue

                ui.warn("[vlm] retriable error; cannot reduce batch further, trying smaller resize scale ...")
                scale_idx += 1
                continue

            raise endpoint_err

        assert out is not None

        if out.strip() == "" or _looks_like_template_leak(out):
            last_err = RuntimeError(f"VLM returned unusable output: {_safe_preview(out, 200)!r}")
            ui.warn("[vlm] output unusable (empty/template). trying smaller resize scale ...")
            ui.err(f"[vlm] Full response: {out}")
            _append_unusable(out)
            scale_idx += 1
            continue

        return out

    if last_err is None:
        raise RuntimeError("VLM failed for unknown reasons (no exception captured).")

    raise last_err
