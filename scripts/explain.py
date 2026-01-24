#!/usr/bin/env python3
"""
explain – use local LLM to explain diffs, logs, code, configs, docs, or data.

USAGE EXAMPLES
--------------

# 1) Explain git diffs from current repo
explain --diff              # staged diff (git diff --cached)
explain --diff --all        # working tree diff (git diff)
explain git                 # alias for --diff

# 2) Pipe a diff
git diff --cached | explain

# 3) Explain logs / text from a file or a pipe
explain some.log
journalctl -u mysvc | explain

# 4) Reuse the last investigate log explicitly
explain log
explain logs

# 5) Explain code / config / docs / data files directly
explain scripts/runi.py
explain config/app.yaml
explain README.md
explain data/report.csv

# 6) Paste manually (interactive)
explain
<paste here>
CTRL+D
"""

import os
import sys
import subprocess

from pathlib import Path
from textwrap import dedent

from .helper.llm import ollama_chat
from .helper.json_utils import strip_json_fence
from .helper.spinner import with_spinner
from .helper.context import warn_if_approaching_context
from .helper.env import load_repo_dotenv
from .helper.colors import Colors
load_repo_dotenv()


BASE_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
DEFAULT_LOG_PATH = LOG_DIR / "investigate-last.log"

# File-type based hints for auto mode
CODE_EXTS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".vue",
    ".rs",
    ".go",
    ".java",
    ".c",
    ".cpp",
    ".cc",
    ".h",
    ".hpp",
    ".cs",
    ".php",
    ".rb",
    ".swift",
    ".kt",
    ".kts",
    ".scala",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
}

CONFIG_EXTS = {
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".env",
    ".conf",
}

DOC_EXTS = {
    ".md",
    ".markdown",
    ".rst",
}

TABLE_EXTS = {
    ".csv",
    ".tsv",
}



# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------


def parse_args(argv: list[str]) -> tuple[str, bool, str | None]:
    """
    Parse CLI arguments.

    Returns:
        (mode, use_all, path_or_none)

    mode ∈ {"auto", "diff", "logs"}:

      auto  - stdin / file / paste (no implicit log reading)
      diff  - read git diff from current repo
      logs  - read last investigate log (INVESTIGATE_LOG or logs/investigate-last.log)

    Supported forms:

      explain
      explain <file>
      explain --diff
      explain --diff --all
      explain git          # alias for --diff
      explain log          # reuse investigate log
      explain logs
    """
    mode = "auto"  # auto-detect: diff vs code vs config vs docs vs table vs logs
    use_all = False
    path: str | None = None

    i = 0
    while i < len(argv):
        arg = argv[i]

        if arg in ("git", "--diff"):
            if mode == "logs":
                print(f"{Colors.c('explain')} {Colors.r('cannot combine git/diff mode with logs mode.')}", file=sys.stderr)
                sys.exit(1)
            mode = "diff"
            i += 1
            continue

        if arg == "--all":
            use_all = True
            i += 1
            continue

        if arg in ("log", "logs", "--log", "--logs"):
            if mode == "diff":
                print(f"{Colors.c('explain')} {Colors.r('cannot combine logs mode with git/diff mode.')}", file=sys.stderr)
                sys.exit(1)
            mode = "logs"
            i += 1
            continue

        if arg in ("-h", "--help"):
            print(__doc__ or "", file=sys.stderr)
            sys.exit(0)

        if arg.startswith("-"):
            print(f"{Colors.c('explain')} {Colors.r(f'unknown option: {arg}')}", file=sys.stderr)
            sys.exit(1)

        # non-flag argument: treat as file path
        if path is None:
            path = arg
        else:
            print(f"{Colors.c('explain')} {Colors.r(f'unexpected extra argument: {arg}')}", file=sys.stderr)
            sys.exit(1)

        i += 1

    if mode != "diff" and use_all:
        print(f"{Colors.c('explain')} {Colors.r('--all is only valid together with --diff/git.')}", file=sys.stderr)
        sys.exit(1)

    if mode in ("diff", "logs") and path is not None:
        print(f"{Colors.c('explain')} {Colors.r('cannot combine a file path with git/logs mode.')}", file=sys.stderr)
        sys.exit(1)

    return mode, use_all, path


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------


def run_git_diff(use_all: bool) -> str:
    """Get diff text: staged (default) or working tree (--all)."""
    cmd = ["git", "diff", "--cached"] if not use_all else ["git", "diff"]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        print(f"{Colors.c('[explain]')} {Colors.r('git not found on PATH.')}", file=sys.stderr)
        sys.exit(1)

    if result.returncode != 0:
        print(f"{Colors.c('[explain]')} {Colors.r('git diff failed:')}\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    diff = result.stdout
    if not diff.strip():
        scope = "staged" if not use_all else "working tree"
        print(f"{Colors.c('[explain]')} {Colors.r(f'No {scope} changes to describe (empty diff).')}", file=sys.stderr)
        sys.exit(1)

    return diff


def read_investigate_log() -> str:
    """Read the last investigate log explicitly."""
    log_path_str = os.getenv("INVESTIGATE_LOG", str(DEFAULT_LOG_PATH))
    log_path = Path(log_path_str)

    if not log_path.exists():
        print(
            f"{Colors.c('[explain]')} {Colors.r(f'No investigate log found at {log_path}.')}\n"
            "          Run your command via 'runi' / 'investigate' first, "
            "or pipe logs/text into 'explain', or pass a file path.",
            file=sys.stderr,
        )
        sys.exit(1)

    return log_path.read_text(encoding="utf-8", errors="ignore")


def read_auto_input(path: str | None) -> str:
    """
    Auto mode:

      1. If stdin has data → use that.
      2. Else, if a file path is provided → read that file.
      3. Else, prompt for interactive paste (no implicit log reading).
    """
    # 1) stdin wins
    if not sys.stdin.isatty():
        return sys.stdin.read()

    # 2) explicit file path
    if path is not None:
        p = Path(path)
        if not p.exists():
            print(f"{Colors.c('[explain]')} {Colors.r(f'File not found: {p}')}", file=sys.stderr)
            sys.exit(1)
        return p.read_text(encoding="utf-8", errors="ignore")

    # 3) interactive paste
    print(f"{Colors.c('[explain]')} {Colors.m('Paste text (logs, diff, code, config, docs, or data), then press Ctrl+D.')}", file=sys.stderr)
    data = sys.stdin.read()
    if not data.strip():
        print(f"{Colors.c('[explain]')} {Colors.r('No input provided.')}", file=sys.stderr)
        sys.exit(1)
    return data


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------


def looks_like_git_diff(text: str) -> bool:
    """Cheap heuristic to recognize a git diff."""
    if "diff --git " in text:
        return True
    lines = text.splitlines()
    for ln in lines[:50]:
        if ln.startswith("diff --git "):
            return True
        if ln.startswith(("+++", "---")) and any(
            line.startswith("diff --git ") for line in lines[:10]
        ):
            return True
    return False


def kind_from_path(path: str | None) -> str | None:
    """
    Infer kind from file extension.

    Returns one of {"code", "config", "docs", "table"} or None.
    """
    if not path:
        return None
    suffix = Path(path).suffix.lower()
    if suffix in CODE_EXTS:
        return "code"
    if suffix in CONFIG_EXTS:
        return "config"
    if suffix in DOC_EXTS:
        return "docs"
    if suffix in TABLE_EXTS:
        return "table"
    return None


def looks_like_json_or_yaml(text: str) -> bool:
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        # very rough JSON-ish
        return True
    # simple YAML-ish: key: value lines
    lines = [ln for ln in text.splitlines() if ln.strip()]
    sample = lines[:20]
    kv_lines = 0
    for ln in sample:
        if ":" in ln and not ln.strip().startswith("#"):
            kv_lines += 1
    return kv_lines >= 3


def looks_like_table(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    first = lines[0]
    if "," in first or "\t" in first:
        # very rough CSV/TSV heuristic
        return True
    return False


def guess_kind_from_content(text: str) -> str:
    """
    Fallback heuristic when we have content but no trusted path.

    Order:
      - diff
      - config (json/yaml-ish)
      - table (csv/tsv-ish)
      - logs (default)
    """
    if looks_like_git_diff(text):
        return "diff"
    if looks_like_json_or_yaml(text):
        return "config"
    if looks_like_table(text):
        return "table"
    return "logs"


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def build_prompts(content: str, kind: str) -> tuple[str, str]:
    """
    kind ∈ {"diff", "logs", "code", "config", "docs", "table"}
    """
    if kind == "diff":
        system_prompt = dedent(
            """
            You are an assistant that explains git diffs for developers.

            Input:
              - A git diff (possibly multiple files, additions/removals/renames).
              - Sometimes diff-like content mixed with a few log lines.

            Your tasks:

              1) Explain what this diff does
                 - Group your explanation by file when helpful.
                 - Describe behavior changes in plain language.
                 - Point out important refactors, new features, or deletions.

              2) Highlight potential problems
                 - Possible bugs or regressions.
                 - Suspicious patterns (e.g., missing error handling, unsafe defaults,
                   magic numbers, race conditions, brittle tests).
                 - Interface or API changes that might break callers.

              3) Suggest improvements
                 - Better structure, naming, or separation of concerns.
                 - Additional tests or checks worth adding.
                 - Any obvious performance or reliability improvements.

            Constraints:
              - Your answer MUST be primarily natural-language prose.
              - You MAY include small diff snippets when necessary,
                but do NOT respond with only a code block.
              - Do NOT re-print the entire diff.
              - If the diff seems trivial or mostly mechanical, say that briefly.
            """
        ).strip()

        user_prompt = (
            "Explain the following git diff, following the tasks above.\n\n"
            "Here is the diff:\n\n"
            "```diff\n"
            f"{content}\n"
            "```"
        )

    elif kind == "code":
        system_prompt = dedent(
            """
            You are an assistant that explains source code for developers.

            Input:
              - A single file of source code (Python, TypeScript, JavaScript, Go,
                Rust, C/C++, C#, PHP, Ruby, Swift, shell, or similar).
              - It may be a script, a module, or an entrypoint.

            Your tasks:

              1) High-level summary
                 - Explain what this code does overall.
                 - Describe the main responsibilities of the script/module.

              2) Walk-through of important pieces
                 - Explain key functions, classes, and control flow.
                 - Call out how inputs are received and how outputs/results are produced.

              3) Potential issues and edge cases
                 - Identify obvious bugs, race conditions, or error-handling gaps.
                 - Mention places where robustness or clarity could be improved.

              4) Suggestions for improvement
                 - Refactoring ideas (extraction, naming, structure).
                 - Testing ideas (what should be unit/integration tested).
                 - Any performance or maintainability concerns.

            Constraints:
              - Your answer MUST be primarily natural-language prose.
              - You MAY include short code snippets to illustrate points,
                but do NOT respond with only a code block.
              - Do NOT just reprint the file.
              - Focus on explanation and reasoning, not reformatting.
            """
        ).strip()

        user_prompt = (
            "Explain the following source code according to the tasks above.\n\n"
            "Here is the code:\n\n"
            "```code\n"
            f"{content}\n"
            "```"
        )

    elif kind == "config":
        system_prompt = dedent(
            """
            You are an assistant that explains configuration / structured data files.

            Input:
              - JSON, YAML, TOML, INI, .env, or similar configuration/data.
              - It may be an application config, service settings, or structured payload.

            Your tasks:

              1) Structural overview
                 - Describe the overall structure: top-level sections/objects and how they relate.
                 - Group related keys/fields into logical clusters (e.g. database, auth, logging).

              2) Key fields and their meaning
                 - Explain important keys and their likely role (endpoints, credentials, timeouts,
                   feature flags, environment settings, etc.).
                 - Highlight defaults and where overrides might matter.

              3) Potential issues
                 - Point out obviously dangerous or surprising values (e.g. debug=true in prod,
                   0.0.0.0 binds, weak timeouts, missing auth).
                 - Identify inconsistent or duplicate settings.

              4) Suggestions
                 - Suggest clearer structure or naming if the config is messy.
                 - Suggest safer defaults or sensible ranges where appropriate.

            Constraints:
              - Your answer MUST be primarily natural-language prose.
              - You MAY include short key examples, but do NOT dump the entire file back.
              - Do NOT invent keys that are not present.
            """
        ).strip()

        user_prompt = (
            "Explain the following configuration / structured data according to the tasks above.\n\n"
            "Here is the content:\n\n"
            "```config\n"
            f"{content}\n"
            "```"
        )

    elif kind == "docs":
        system_prompt = dedent(
            """
            You are an assistant that explains Markdown / documentation files.

            Input:
              - A Markdown or similar documentation file (README, spec, notes, etc.).

            Your tasks:

              1) Outline
                 - Summarize the main sections and their purpose.
                 - Provide a short high-level overview of what this document is about.

              2) Key points
                 - Highlight the most important ideas, instructions, or decisions.
                 - Group related topics (setup, usage, API, architecture, constraints).

              3) Gaps or unclear areas
                 - Point out sections that might be confusing or underspecified.
                 - Suggest where examples, diagrams, or more detail would help.

              4) Suggestions for improvement
                 - Propose improvements to structure, ordering, and clarity.
                 - Call out outdated-looking sections if any.

            Constraints:
              - Your answer MUST be primarily natural-language prose.
              - Do NOT just restate every bullet line-by-line.
              - Focus on the big picture and practical takeaways.
            """
        ).strip()

        user_prompt = (
            "Explain the following documentation / Markdown file according to the tasks above.\n\n"
            "Here is the content:\n\n"
            "```markdown\n"
            f"{content}\n"
            "```"
        )

    elif kind == "table":
        system_prompt = dedent(
            """
            You are an assistant that explains tabular data (CSV/TSV).

            Input:
              - A CSV/TSV-like text with a header row and data rows.

            Your tasks:

              1) Column overview
                 - Describe what each column appears to represent.
                 - Group related columns (identifiers, metrics, timestamps, flags).

              2) Data characteristics
                 - Comment on obvious patterns (e.g. ranges, monotonic fields, boolean flags).
                 - Mention any apparent groupings or categories.

              3) Potential issues
                 - Point out missing/empty values, obvious inconsistencies, or weird outliers
                   if they are visible in the sample.
                 - Call out columns that may be redundant or ambiguous.

              4) Suggestions
                 - Suggest better naming where columns are unclear.
                 - Suggest additional derived fields or aggregations that might be useful.

            Constraints:
              - Your answer MUST be primarily natural-language prose.
              - You MAY refer to individual rows as examples, but do NOT dump the whole table back.
              - If the file is very large, treat the visible content as a sample.
            """
        ).strip()

        user_prompt = (
            "Explain the following tabular data (CSV/TSV) according to the tasks above.\n\n"
            "Here is the content:\n\n"
            "```table\n"
            f"{content}\n"
            "```"
        )

    else:  # "logs"
        system_prompt = dedent(
            """
            You are a precise assistant that explains logs and text traces.

            Input:
              - Application or server logs, stack traces, or textual diagnostics.
              - Possibly mixed with configuration snippets or code fragments.

            Your tasks:

              1) Summary
                 - Provide a concise summary of what is happening.
                 - Mention the main operations, requests, or phases.

              2) Errors & warnings
                 - Identify the most important errors or warning patterns.
                 - Quote only a few key lines (no giant dumps).
                 - Explain what they mean and why they matter.

              3) Root cause & reasoning
                 - Suggest the most likely root cause(s) based on the evidence.
                 - Call out uncertainties explicitly instead of guessing.

              4) Next steps / improvements
                 - Suggest concrete next steps: commands to run, files to inspect,
                   configuration to double-check, or logs to enable.
                 - Mention any obvious robustness or observability improvements.

            Constraints:
              - Your answer MUST be primarily natural-language prose.
              - You MAY include short quoted lines, but do NOT respond with only a code block.
              - Do NOT invent logs or stack traces that do not exist.
              - Do NOT give generic advice that ignores the actual content.
            """
        ).strip()

        user_prompt = (
            "Explain the following logs / text according to the tasks above.\n\n"
            "Here is the content (newest lines are usually last):\n\n"
            "```text\n"
            f"{content}\n"
            "```"
        )

    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# Model call
# ---------------------------------------------------------------------------


def call_model(system_prompt: str, user_prompt: str, label: str) -> str:
    def _call() -> str:
        raw = ollama_chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=os.getenv("EXPLAIN_MODEL"),
            num_ctx=16000,
            timeout=180,
        )
        # For explain: we want plain text; fences/outer quotes are noise.
        return strip_json_fence(raw)

    try:
        return with_spinner(Colors.c(label), _call)
    except Exception as e:
        print(f"{Colors.c('[explain]')} {Colors.r(f'Error calling Ollama: {e}')}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    mode, use_all, path = parse_args(sys.argv[1:])

    if mode == "diff":
        content = run_git_diff(use_all)
        kind = "diff"
    elif mode == "logs":
        content = read_investigate_log()
        kind = "logs"
    else:  # auto
        content = read_auto_input(path)
        # Prefer a strong diff signal first
        if looks_like_git_diff(content):
            kind = "diff"
        else:
            # Try path-based hint, then fallback content-based
            kind = kind_from_path(path) or guess_kind_from_content(content)

    if not content.strip():
        print(f"{Colors.c('[explain]')} {Colors.r('No input to analyze.')}", file=sys.stderr)
        sys.exit(1)

    warn_if_approaching_context("explain", content)

    system_prompt, user_prompt = build_prompts(content, kind)
    answer = call_model(system_prompt, user_prompt, "explain")
    print(answer)


if __name__ == "__main__":
    main()
