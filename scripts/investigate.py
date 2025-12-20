#!/usr/bin/env python3
import os
import sys
from pathlib import Path
from textwrap import dedent

import requests
from helper.ollama_utils import resolve_ollama_url

DEFAULT_LINES = 100
LINES_PER_PAGE = 80

BASE_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

DEFAULT_LOG_PATH = LOG_DIR / "investigate-last.log"


def read_logs(lines_needed: int) -> str:
    # 1. If data is piped in, use that
    if not sys.stdin.isatty():
        data = sys.stdin.read().splitlines()
        return "\n".join(data[-lines_needed:])

    # 2. Otherwise, use the tracked log file (default under repo/logs/)
    log_path_str = os.getenv("INVESTIGATE_LOG", str(DEFAULT_LOG_PATH))
    log_path = Path(log_path_str)

    if log_path.exists():
        with log_path.open("r", encoding="utf-8", errors="ignore") as f:
            data = f.read().splitlines()
        return "\n".join(data[-lines_needed:])

    print(
        f"No piped input and no tracked log found at {log_path}. "
        "Did you run via 'runi' or pipe logs into 'investigate'?",
        file=sys.stderr,
    )
    sys.exit(1)


def main() -> None:
    if len(sys.argv) > 1:
        try:
            pages = int(sys.argv[1])
            lines_needed = pages * LINES_PER_PAGE
        except ValueError:
            print("Usage: investigate [pages]", file=sys.stderr)
            sys.exit(1)
    else:
        lines_needed = DEFAULT_LINES

    logs = read_logs(lines_needed)

    if not logs.strip():
        print("No logs to analyze.", file=sys.stderr)
        sys.exit(1)

    ollama_url = resolve_ollama_url("http://localhost:11434")
    model = os.getenv("INVESTIGATE_MODEL", "llama3.1:8b")

    system_prompt = dedent(
        """
        You are a precise debugging assistant analyzing logs.

        DO:
          - Identify primary error(s)
          - Quote 10-20 relevant lines only
          - Provide likely cause(s)
          - Suggest actionable next steps or commands

        DO NOT:
          - Include irrelevant summary
          - Invent logs that do not exist
        """
    ).strip()

    user_prompt = f"Here are the logs (newest last):\n\n```log\n{logs}\n```"

    payload = {
        "model": model,
        "num_ctx": 16000,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }

    try:
        resp = requests.post(
            f"{ollama_url}/api/chat",
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        print(data["message"]["content"])
    except Exception as e:
        print(f"Error calling Ollama: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
