#!/usr/bin/env python3
"""
voice-capture — local speech-to-text using Qwen2.5-Omni.

USAGE
  # 1) Transcribe an existing audio file
  voice-capture /path/to/audio.wav

  # 2) Record N seconds then transcribe (requires arecord in WSL audio setup)
  voice-capture record --seconds 10

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

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

from .helper.colors import Colors

# from faster_whisper import WhisperModel


_PUNCT_RE = re.compile(r"[^\w\s']+", re.UNICODE)  # keep apostrophes in contractions

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




def literalize(text: str) -> str:
    t = text.strip().lower()
    t = _PUNCT_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def convert_to_wav(src_path: str, dst_path: str, sample_rate: int = 16000) -> None:
    """
    Convert audio file to 16kHz mono WAV using ffmpeg.
    Useful for normalizing browser-recorded audio (webm/ogg).
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i", src_path,
        "-ac", "1",
        "-ar", str(sample_rate),
        "-vn",
        dst_path,
    ]
    try:
        p = subprocess.run(
            cmd,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        if p.returncode != 0:
            err = (p.stderr or "").strip()
            raise RuntimeError(f"ffmpeg failed with exit code {p.returncode}: {err}")
    except FileNotFoundError:
        raise RuntimeError("ffmpeg not found. Please install it (e.g., sudo apt install ffmpeg).")


from .helper.omni_helper import OmniHelper

def transcribe_file(
    audio_path: str,
    *,
    model_name: str | None = None,
    lang: Optional[str] = None,
    device: str | None = None,
    compute_type: str | None = None,
) -> Tuple[str, str, Dict[str, Any]]:
    """
    Import-friendly transcription API using Qwen2.5-Omni.

    Returns: (raw_text, literal_text, meta)
    """
    # Use OmniHelper for transcription
    try:
        raw_text = OmniHelper.transcribe(audio_path)
    except Exception as e:
        print(f"{Colors.r('Omni ASR Error:')} {e}", file=sys.stderr)
        raise

    literal_text = literalize(raw_text)

    meta: Dict[str, Any] = {
        "audio": audio_path,
        "language": lang,
        "duration": None,
        "model": os.getenv("OMNI_MODEL", "Qwen/Qwen2.5-Omni-3B"),
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


def parse_args() -> Args:
    parser = argparse.ArgumentParser(
        description="Local speech-to-text using faster-whisper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    # Subcommands: 'file' (default implicit) or 'record'
    subparsers = parser.add_subparsers(dest="command", help="Mode of operation")
    
    # Record mode
    parser_record = subparsers.add_parser("record", help="Record audio from microphone")
    parser_record.add_argument("--seconds", type=int, default=10, help="Duration to record (seconds)")
    
    # Common args
    for p in [parser, parser_record]:
        p.add_argument("--model", default=os.getenv("WHISPER_MODEL", "small"), help="Whisper model size")
        p.add_argument("--lang", default=os.getenv("WHISPER_LANG", "en"), help="Language code (e.g. en)")
        p.add_argument("--device", default=os.getenv("WHISPER_DEVICE", "cpu"), help="Device (cpu, cuda)")
        p.add_argument("--compute", dest="compute_type", default=os.getenv("WHISPER_COMPUTE_TYPE", "int8"), help="Compute type (int8, float16)")
        p.add_argument("--text", dest="text_mode", choices=["json", "raw", "literal"], default="json", help="Output format")

    # File mode arguments (applied to main parser)
    parser.add_argument("file_path", nargs="?", help="Path to audio file (for file mode)")

    args = parser.parse_args()

    if args.command == "record":
        return Args(
            mode="record",
            target=None,
            seconds=args.seconds,
            model=args.model,
            lang=args.lang,
            device=args.device,
            compute_type=args.compute_type,
            text_mode=args.text_mode,
        )
    
    # Default to file mode
    if not args.file_path:
        parser.print_help()
        sys.exit(1)

    return Args(
        mode="file",
        target=Path(args.file_path),
        seconds=None,
        model=args.model,
        lang=args.lang,
        device=args.device,
        compute_type=args.compute_type,
        text_mode=args.text_mode,
    )


def main() -> None:
    try:
        args = parse_args()

        if args.mode == "record":
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            
            try:
                print(f"{Colors.c('[voice-capture]')} Recording for {args.seconds} seconds...", file=sys.stderr)
                record_wav(args.seconds or 10, tmp_path)
                audio_path = str(tmp_path)
            except Exception as e:
                print(f"{Colors.r('[voice-capture]')} Recording failed: {e}", file=sys.stderr)
                if tmp_path.exists():
                    os.unlink(tmp_path)
                sys.exit(1)
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

        # Cleanup temp recording
        if args.mode == "record" and os.path.exists(audio_path):
            os.unlink(audio_path)

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

    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"{Colors.r('Error:')} {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
