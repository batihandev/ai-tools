#!/usr/bin/env python3
import os
import sys
from pathlib import Path
from textwrap import dedent

from .helper.llm import ollama_chat
from .helper.json_utils import strip_json_fence
from .helper.spinner import with_spinner
from .helper.context import warn_if_approaching_context
from .helper.env import load_repo_dotenv
from .helper.colors import Colors
load_repo_dotenv()

DEFAULT_LINES = 100
LINES_PER_PAGE = 80

BASE_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

DEFAULT_LOG_PATH = LOG_DIR / "investigate-last.log"


# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------


def parse_args(argv: list[str]) -> tuple[int, str, str | None]:
    """
    Parse CLI arguments.

    Returns:
        (lines, mode, path_or_none)

    Supported forms:
        investigate
        investigate -n 300
        investigate some.log
        investigate -n 200 some.log
        investigate 3               # backward-compat "pages" (3 * LINES_PER_PAGE)
        investigate --mode summary
    """
    lines: int | None = None
    mode = "debug"
    path: str | None = None

    i = 0
    while i < len(argv):
        arg = argv[i]

        if arg in ("-n", "--lines"):
            if i + 1 >= len(argv):
                print(f"{Colors.c('investigate')} {Colors.r('-n/--lines requires an integer value')}", file=sys.stderr)
                sys.exit(1)
            try:
                lines = int(argv[i + 1])
            except ValueError:
                print(f"{Colors.c('investigate')} {Colors.r('-n/--lines value must be an integer')}", file=sys.stderr)
                sys.exit(1)
            i += 2
            continue

        if arg == "--mode":
            if i + 1 >= len(argv):
                print(f"{Colors.c('investigate')} {Colors.r('--mode requires a value')}", file=sys.stderr)
                sys.exit(1)
            mode_val = argv[i + 1]
            if mode_val not in ("debug", "summary", "blame"):
                print(
                    f"{Colors.c('investigate')} {Colors.r('--mode must be one of: debug, summary, blame')}",
                    file=sys.stderr,
                )
                sys.exit(1)
            mode = mode_val
            i += 2
            continue

        if arg.startswith("-"):
            print(f"{Colors.c('investigate')} {Colors.r(f'unknown option: {arg}')}", file=sys.stderr)
            print(f"Usage: {Colors.bold('investigate')} [-n LINES] [--mode debug|summary|blame] [LOG_FILE]", file=sys.stderr)
            sys.exit(1)

        # Non-flag argument:
        # If it's a pure integer and we don't have lines yet, treat as "pages"
        if lines is None and arg.isdigit():
            pages = int(arg)
            lines = pages * LINES_PER_PAGE
        elif path is None:
            path = arg
        else:
            print(f"{Colors.c('investigate')} {Colors.r(f'unexpected extra argument: {arg}')}", file=sys.stderr)
            sys.exit(1)

        i += 1

    if lines is None:
        lines = DEFAULT_LINES

    return lines, mode, path


# ---------------------------------------------------------------------------
# Log loading
# ---------------------------------------------------------------------------


def read_logs(lines_needed: int, path: str | None) -> str:
    """
    Determine log source:

    1. If stdin is piped, use that (ignore path/env).
    2. Else, if a path is given, read from that file.
    3. Else, use the tracked log file (env or default under repo/logs/).
    """
    # 1. If data is piped in, use that
    if not sys.stdin.isatty():
        data = sys.stdin.read().splitlines()
        return "\n".join(data[-lines_needed:])

    # 2. If explicit path is given, use that
    if path is not None:
        log_path = Path(path)
    else:
        # 3. Use the tracked log file (default under repo/logs/)
        log_path_str = os.getenv("INVESTIGATE_LOG", str(DEFAULT_LOG_PATH))
        log_path = Path(log_path_str)

    if log_path.exists():
        with log_path.open("r", encoding="utf-8", errors="ignore") as f:
            data = f.read().splitlines()
        return "\n".join(data[-lines_needed:])

    print(
        f"{Colors.r('No piped input and no log found at')} {log_path}. "
        "Did you run via 'runi' or pipe logs into 'investigate'?",
        file=sys.stderr,
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def build_system_prompt(mode: str) -> str:
    if mode == "summary":
        return dedent(
            """
            You are a precise log summarization assistant.

            Your goals:
              - Provide a high-level summary of what these logs show.
              - Highlight key events, errors, warnings, and time ranges.
              - Group related messages into a few clear bullet points.
              - Mention the most important error(s) and their impact.

            Do not:
              - Invent logs or details that are not present.
              - Over-quote; prefer short snippets or line ranges.
            """
        ).strip()

    if mode == "blame":
        return dedent(
            """
            You are a precise debugging assistant focusing on responsibility ("blame").

            Your goals:
              - Identify the most likely component, service, module, or change
                that is responsible for the error(s) in these logs.
              - Quote 5-15 highly relevant lines to support your conclusion.
              - Explain why this component is likely at fault.
              - Suggest concrete next steps (e.g., which file/endpoint/config
                to inspect, or which team/owner should look).

            Do not:
              - Invent logs or stack traces that do not exist.
              - Accuse people; focus on code, services, or configuration.
            """
        ).strip()

    # default: "debug"
    return dedent(
        """
        You are a precise debugging assistant analyzing logs.

        Your goals:
          - Identify the primary error(s) or failure mode(s).
          - Quote 10-20 relevant lines only (no giant dumps).
          - Explain likely root cause(s) in plain language.
          - Suggest concrete, actionable next steps or commands
            (e.g., tests to run, files to inspect, config to check).

        Do not:
          - Invent logs or details that do not exist.
          - Provide generic advice that ignores the actual log content.
        """
    ).strip()


def build_prompts(logs: str, mode: str) -> tuple[str, str]:
    system_prompt = build_system_prompt(mode)
    user_prompt = f"Here are the logs (newest last):\n\n```log\n{logs}\n```"
    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# Model call
# ---------------------------------------------------------------------------


def call_model(system_prompt: str, user_prompt: str) -> str:
    def _call() -> str:
        raw = ollama_chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=os.getenv("INVESTIGATE_MODEL"),
            num_ctx=16000,
            timeout=120,
        )
        return strip_json_fence(raw)

    try:
        return with_spinner(Colors.c("investigate"), _call)
    except Exception as e:
        print(f"Error calling Ollama: {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    lines_needed, mode, path = parse_args(sys.argv[1:])

    logs = read_logs(lines_needed, path)

    if not logs.strip():
        print(Colors.r("No logs to analyze."), file=sys.stderr)
        sys.exit(1)

    # Shared soft context warning
    warn_if_approaching_context("investigate", logs)

    system_prompt, user_prompt = build_prompts(logs, mode)
    answer = call_model(system_prompt, user_prompt)
    print(answer)


if __name__ == "__main__":
    main()
