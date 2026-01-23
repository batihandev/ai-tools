#!/usr/bin/env python3
"""
voice-capture — local speech-to-text using faster-whisper.

USAGE
  # 1) Transcribe an existing audio file
  voice-capture /path/to/audio.wav

  # 2) Record N seconds then transcribe (requires arecord in WSL audio setup)
  voice-capture record 10

  # 3) Override model size / language
  voice-capture /path/to/audio.wav --model small --lang en

  # 4) Output plain text only (literal or raw)
  voice-capture /path/to/audio.wav --text raw
  voice-capture /path/to/audio.wav --text literal

NOTES
  - "raw" is the direct transcription output.
  - "literal" removes punctuation and lowercases to reduce the model “polish”.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

from .helper.colors import Colors

from faster_whisper import WhisperModel

_PUNCT_RE = re.compile(r"[^\w\s']+", re.UNICODE)  # keep apostrophes in contractions

_model_singleton: WhisperModel | None = None
_model_sig: tuple[str, str, str] | None = None  # (model_name, device, compute_type)


@dataclass(frozen=True)
class Args:
    mode: str               # "file" or "record"
    target: Path | None     # audio path if mode=file
    seconds: int | None     # record duration if mode=record
    model: str              # tiny/base/small/medium/large-v3 (or local path)
    lang: Optional[str]     # e.g. "en"
    device: str             # "cpu" or "cuda"
    compute_type: str       # "int8", "int8_float16", "float16", etc.
    text_mode: str          # "json" | "raw" | "literal"


def _get_model(model_name: str, device: str, compute_type: str) -> WhisperModel:
    """
    Keep a singleton model in-process (FastAPI benefits a lot).
    If settings change, re-initialize.
    """
    global _model_singleton, _model_sig
    sig = (model_name, device, compute_type)
    if _model_singleton is None or _model_sig != sig:
        _model_singleton = WhisperModel(model_name, device=device, compute_type=compute_type)
        _model_sig = sig
    return _model_singleton


def literalize(text: str) -> str:
    t = text.strip().lower()
    t = _PUNCT_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def transcribe_file(
    audio_path: str,
    *,
    model_name: str | None = None,
    lang: Optional[str] = None,
    device: str | None = None,
    compute_type: str | None = None,
) -> Tuple[str, str, Dict[str, Any]]:
    """
    Import-friendly transcription API.

    Returns: (raw_text, literal_text, meta)
    """
    model_name = model_name or os.getenv("WHISPER_MODEL", "small")
    lang = lang if lang is not None else (os.getenv("WHISPER_LANG", "en") or None)
    device = device or os.getenv("WHISPER_DEVICE", "cpu")
    compute_type = compute_type or os.getenv("WHISPER_COMPUTE_TYPE", "int8")

    m = _get_model(model_name, device=device, compute_type=compute_type)

    segments, info = m.transcribe(
        audio_path,
        language=lang,
        vad_filter=True,     # removes long silences (does not rewrite text)
        beam_size=1,         # fast; raise for accuracy if you want
        best_of=1,
        temperature=0.0,
    )

    raw_parts: list[str] = []
    for s in segments:
        t = (s.text or "").strip()
        if t:
            raw_parts.append(t)

    raw_text = " ".join(raw_parts).strip()
    literal_text = literalize(raw_text)

    meta: Dict[str, Any] = {
        "audio": audio_path,
        "language": getattr(info, "language", None),
        "duration": getattr(info, "duration", None),
        "model": model_name,
        "device": device,
        "compute_type": compute_type,
    }

    return raw_text, literal_text, meta


def record_wav(seconds: int, out_path: Path) -> None:
    # Requires WSL audio configured. If this fails, record on Windows and pass the file instead.
    cmd = [
        "arecord",
        "-f", "S16_LE",
        "-r", "16000",
        "-c", "1",
        "-d", str(seconds),
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def parse_args(argv: list[str]) -> Args:
    model = os.getenv("WHISPER_MODEL", "small")
    lang = os.getenv("WHISPER_LANG", "en")
    device = os.getenv("WHISPER_DEVICE", "cpu")
    compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    text_mode = "json"

    if not argv or any(a in ("-h", "--help", "help") for a in argv):
        print(__doc__.strip())
        sys.exit(0)

    tokens = list(argv)

    # flags
    i = 0
    cleaned: list[str] = []
    while i < len(tokens):
        a = tokens[i]
        if a == "--model":
            if i + 1 >= len(tokens):
                print(f"{Colors.c('[voice-capture]')} {Colors.r('Missing value for --model')}", file=sys.stderr)
                sys.exit(1)
            model = tokens[i + 1]
            i += 2
            continue
        if a == "--lang":
            if i + 1 >= len(tokens):
                print(f"{Colors.c('[voice-capture]')} {Colors.r('Missing value for --lang')}", file=sys.stderr)
                sys.exit(1)
            lang = tokens[i + 1]
            i += 2
            continue
        if a == "--device":
            if i + 1 >= len(tokens):
                print(f"{Colors.c('[voice-capture]')} {Colors.r('Missing value for --device')}", file=sys.stderr)
                sys.exit(1)
            device = tokens[i + 1]
            i += 2
            continue
        if a == "--compute":
            if i + 1 >= len(tokens):
                print(f"{Colors.c('[voice-capture]')} {Colors.r('Missing value for --compute')}", file=sys.stderr)
                sys.exit(1)
            compute_type = tokens[i + 1]
            i += 2
            continue
        if a == "--text":
            if i + 1 >= len(tokens):
                print(f"{Colors.c('[voice-capture]')} {Colors.r('Missing value for --text')}", file=sys.stderr)
                sys.exit(1)
            text_mode = tokens[i + 1]  # raw | literal | json
            i += 2
            continue

        cleaned.append(a)
        i += 1

    if not cleaned:
        print(f"{Colors.c('[voice-capture]')} {Colors.r('Missing args')}", file=sys.stderr)
        sys.exit(1)

    if cleaned[0] == "record":
        seconds = int(cleaned[1]) if len(cleaned) > 1 else 10
        return Args(
            mode="record",
            target=None,
            seconds=seconds,
            model=model,
            lang=lang if lang else None,
            device=device,
            compute_type=compute_type,
            text_mode=text_mode,
        )

    return Args(
        mode="file",
        target=Path(cleaned[0]),
        seconds=None,
        model=model,
        lang=lang if lang else None,
        device=device,
        compute_type=compute_type,
        text_mode=text_mode,
    )


def main() -> None:
    args = parse_args(sys.argv[1:])

    if args.mode == "record":
        tmp = Path("/tmp/voice_capture.wav")
        record_wav(args.seconds or 10, tmp)
        audio_path = str(tmp)
    else:
        audio = args.target
        if audio is None or not audio.exists():
            print(f"{Colors.c('[voice-capture]')} {Colors.r(f'Not found: {audio}')}", file=sys.stderr)
            sys.exit(1)
        audio_path = str(audio)

    raw_text, literal_text, meta = transcribe_file(
        audio_path,
        model_name=args.model,
        lang=args.lang,
        device=args.device,
        compute_type=args.compute_type,
    )

    if args.text_mode == "raw":
        print(raw_text)
        return
    if args.text_mode == "literal":
        print(literal_text)
        return

    print(json.dumps(
        {
            "audio": meta.get("audio"),
            "language": meta.get("language"),
            "duration": meta.get("duration"),
            "raw_text": raw_text,
            "literal_text": literal_text,
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
