#!/usr/bin/env python3
import os
import sys
import subprocess
from textwrap import dedent
import threading
import time

import requests
from helper.ollama_utils import resolve_ollama_url


"""
ai-commit – suggest git commit messages using local LLM (Llama 3.1:8b).

USAGE

  # 1) Default: use staged changes (git diff --cached), interactive menu
  ai-commit

  # 2) Use unstaged working tree changes instead (git diff)
  ai-commit --all
"""

MAX_DIFF_CHARS = 12000  # keep under model context comfortably


# ---------------------------------------------------------------------------
# Diff helpers
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
        print("[ai-commit] git not found on PATH.", file=sys.stderr)
        sys.exit(1)

    if result.returncode != 0:
        print(
            f"[ai-commit] git diff failed:\n{result.stderr}",
            file=sys.stderr,
        )
        sys.exit(1)

    diff = result.stdout
    if not diff.strip():
        scope = "staged" if not use_all else "working tree"
        print(f"[ai-commit] No {scope} changes to describe.", file=sys.stderr)
        sys.exit(1)

    if len(diff) > MAX_DIFF_CHARS:
        truncated_note = (
            f"\n\n[ai-commit] NOTE: diff truncated from "
            f"{len(diff)} to {MAX_DIFF_CHARS} characters.\n"
        )
        diff = diff[:MAX_DIFF_CHARS] + "\n\n... [TRUNCATED] ..." + truncated_note

    return diff


def estimate_summary_limit(diff: str) -> int | None:
    """
    Derive a soft summary length limit from diff size.

    Small change  -> ~72
    Medium change -> ~100
    Large change  -> ~120
    Huge          -> no hard limit (None)
    """
    file_count = diff.count("diff --git")
    added = diff.count("\n+")
    removed = diff.count("\n-")
    total_changes = added + removed

    if total_changes < 30 and file_count <= 1:
        return 72
    if total_changes < 150 and file_count <= 5:
        return 100
    if total_changes < 800 and file_count <= 20:
        return 120
    return None


def analyze_change_kind(diff: str) -> str:
    """
    Classify change as 'additive', 'removal', or 'mixed'.

    We look at unified diff lines:
      - added lines start with '+' but not '+++ '
      - removed lines start with '-' but not '--- '
    """
    added_code = 0
    removed_code = 0

    for line in diff.splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            continue
        if line.startswith("+"):
            added_code += 1
        elif line.startswith("-"):
            removed_code += 1

    if added_code > 0 and removed_code == 0:
        return "additive"
    if removed_code > 0 and added_code == 0:
        return "removal"
    return "mixed"


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def build_prompt(diff: str) -> tuple[str, str]:
    limit = estimate_summary_limit(diff)
    change_kind = analyze_change_kind(diff)
    new_files = extract_new_files(diff)

    if limit is not None:
        summary_req = (
            f"- First line must be a short imperative summary, "
            f"preferably <= {limit} characters.\n"
        )
    else:
        summary_req = (
            "- First line must be a concise imperative summary; "
            "no strict character limit, but keep it readable.\n"
        )

    if change_kind == "additive":
        change_hint = (
            "- All changes are additions (mostly new files / new lines). "
            "Do NOT start the summary with verbs like 'Fix' or 'Refactor'. "
            "Prefer 'Add', 'Introduce', 'Create', etc.\n"
        )
    elif change_kind == "removal":
        change_hint = (
            "- Changes are removals. Prefer verbs like 'Remove', 'Drop', "
            "'Delete', not 'Fix'.\n"
        )
    else:
        change_hint = ""

    if new_files:
        files_list = "\n".join(f"    - {path}" for path in new_files)
        files_hint = (
            "New files detected in this diff:\n"
            f"{files_list}\n"
            "- In the commit message BODY, you MUST include at least one bullet\n"
            "  for EACH of the files above, in the exact format:\n"
            "      - <path>: <very short purpose/role>\n"
            "- Do not just list all files in the summary line; the bullets\n"
            "  are required and must mention each file separately.\n"
        )
    else:
        files_hint = ""

    system_prompt = dedent(
        f"""
        You are an assistant that writes concise, high-quality git commit messages.

        Requirements:
          {summary_req.rstrip()}
          {change_hint.rstrip()}
          {files_hint.rstrip()}
          - Use present tense, imperative style (e.g., "Add CLI toolbox" or "Introduce helpers").
          - Focus on what changed and why, not how.
          - Treat input as a git diff (unified format).

        Output FORMAT (very important):
          1) Line 1: single-line summary (imperative).
          2) Line 2: blank.
          3) Next lines: one bullet per new file in the form:
                 - path/to/file.ext: short purpose/role
             (exactly one bullet for EACH new file listed above).
          4) Optional extra bullets AFTER that if you want.

        Output rules:
          - Return ONLY the commit message text, no backticks, no markdown fences.
          - Do NOT say things like "Here is a commit message" or "Let me know".
          - If you omit bullets for any new file, your answer is incorrect.
        """
    ).strip()

    # Put the file list also into the user prompt so it’s close to the actual task
    if new_files:
        files_for_user = "\n".join(f"- {p}" for p in new_files)
        files_section = (
            "New files you MUST cover in the body bullets:\n"
            f"{files_for_user}\n\n"
        )
    else:
        files_section = ""

    user_prompt = (
        "Generate a commit message for the following git diff.\n\n"
        f"{files_section}"
        "Remember the required format: summary line, blank line, then one\n"
        "bullet '- path: purpose' for EACH new file.\n\n"
        "Here is the diff:\n"
        "```diff\n"
        f"{diff}\n"
        "```"
    )

    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# Model + spinner + cleaning
# ---------------------------------------------------------------------------

def _with_spinner(label: str, fn):
    """Run fn() while showing a small spinner on stderr."""
    stop_flag = {"stop": False}

    def spinner():
        symbols = "|/-\\"
        idx = 0
        while not stop_flag["stop"]:
            sys.stderr.write(f"\r[{label}] " + symbols[idx % 4])
            sys.stderr.flush()
            idx += 1
            time.sleep(0.1)
        sys.stderr.write(f"\r[{label}] done   \n")
        sys.stderr.flush()

    thread = threading.Thread(target=spinner, daemon=True)
    thread.start()
    try:
        return fn()
    finally:
        stop_flag["stop"] = True
        thread.join()

def extract_new_files(diff: str) -> list[str]:
    """
    Extract paths of files that are newly added in this diff.

    Looks for patterns like:
      diff --git a/path b/path
      new file mode 100644
    """
    new_files = set()
    current_file = None

    for line in diff.splitlines():
        if line.startswith("diff --git"):
            parts = line.split()
            if len(parts) >= 4:
                b_part = parts[3]  # e.g., "b/scripts/ai-commit.py"
                if b_part.startswith("b/"):
                    current_file = b_part[2:]
                else:
                    current_file = b_part
            else:
                current_file = None
        elif line.startswith("new file mode") and current_file:
            new_files.add(current_file)

    return sorted(new_files)

def clean_commit_message(text: str) -> str:
    """Strip obvious meta phrases / fences if the model misbehaves."""
    msg = text.strip()

    # If the model wrapped in ```...``` take inner block
    if "```" in msg:
        parts = msg.split("```")
        if len(parts) >= 3:
            msg = parts[1].strip() if parts[0].strip() == "" else parts[1].strip()

    # Remove surrounding quotes/backticks on single line
    if msg.startswith(("`", '"', "'")) and msg.endswith(("`", '"', "'")):
        msg = msg[1:-1].strip()

    lines = [ln.rstrip() for ln in msg.splitlines()]

    # Drop leading meta lines like "Here is a commit message:"
    while lines and any(
        lines[0].lower().startswith(prefix)
        for prefix in (
            "here is a commit message",
            "here is the commit message",
            "here's a commit message",
            "here is a suitable commit message",
            "here's a suitable commit message",
            "suggested commit message",
            "commit message:",
        )
    ):
        lines.pop(0)

    # Drop trailing meta lines with "let me know"
    while lines and "let me know" in lines[-1].lower():
        lines.pop()

    return "\n".join(lines).strip()


def call_model(system_prompt: str, user_prompt: str) -> str:
    """Call local Ollama to generate the commit message, with spinner."""
    ollama_url = resolve_ollama_url("http://localhost:11434")
    model = os.getenv("AI_COMMIT_MODEL", os.getenv("INVESTIGATE_MODEL", "llama3.1:8b"))

    payload = {
        "model": model,
        "num_ctx": 16000,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }

    def _call():
        resp = requests.post(
            f"{ollama_url}/api/chat",
            json=payload,
            timeout=180,
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data["message"]["content"]
        return clean_commit_message(raw)

    try:
        return _with_spinner("ai-commit generating", _call)
    except Exception as e:
        print(f"[ai-commit] Error calling Ollama: {e}", file=sys.stderr)
        sys.exit(1)


def paraphrase_message(original: str) -> str:
    """Ask the model to rephrase the commit message."""
    ollama_url = resolve_ollama_url("http://localhost:11434")
    model = os.getenv("AI_COMMIT_MODEL", os.getenv("INVESTIGATE_MODEL", "llama3.1:8b"))

    system_prompt = dedent(
        """
        You act as a commit-message rewriter.

        Rewrite the provided commit message:

          - keep the same meaning and intent
          - imperative, present tense
          - concise but clear
          - optional wrapped body lines allowed

        Output:
          - ONLY the rewritten commit message text.
          - No commentary, backticks, or explanations.
        """
    ).strip()

    user_prompt = (
        "Rewrite the following git commit message:\n\n"
        f"{original}\n"
    )

    payload = {
        "model": model,
        "num_ctx": 4096,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }

    def _call():
        resp = requests.post(
            f"{ollama_url}/api/chat",
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data["message"]["content"]
        return clean_commit_message(raw)

    try:
        return _with_spinner("ai-commit paraphrasing", _call)
    except Exception as e:
        print(f"[ai-commit] Paraphrase failed: {e}", file=sys.stderr)
        return original


# ---------------------------------------------------------------------------
# Clipboard helper
# ---------------------------------------------------------------------------

def copy_to_clipboard(text: str) -> bool:
    """
    Best-effort clipboard copy.

    Tries, in order:
      - wl-copy (Wayland)
      - xclip (X11)
      - xsel (X11)
      - pbcopy (macOS)
      - clip.exe (WSL on Windows)
    """
    candidates = [
        (["wl-copy"], "wl-copy"),
        (["xclip", "-selection", "clipboard"], "xclip"),
        (["xsel", "--clipboard", "--input"], "xsel"),
        (["pbcopy"], "pbcopy"),
        (["clip.exe"], "clip.exe"),
    ]

    for cmd, label in candidates:
        try:
            proc = subprocess.run(
                cmd,
                input=text,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if proc.returncode == 0:
                print(
                    f"[ai-commit] Commit command copied to clipboard via {label}.",
                    file=sys.stderr,
                )
                return True
        except FileNotFoundError:
            continue
        except Exception:
            continue

    print(
        "[ai-commit] Could not copy to clipboard "
        "(no wl-copy/xclip/xsel/pbcopy/clip.exe found).",
        file=sys.stderr,
    )
    return False


# ---------------------------------------------------------------------------
# CLI + menu
# ---------------------------------------------------------------------------

def parse_args(argv: list[str]) -> bool:
    """Return use_all (True if --all)."""
    use_all = False

    for arg in argv:
        if arg == "--all":
            use_all = True
        elif arg in ("-h", "--help"):
            print(__doc__ or "")
            sys.exit(0)
        else:
            print(f"[ai-commit] Unknown argument: {arg}", file=sys.stderr)
            print("Usage: ai-commit [--all]", file=sys.stderr)
            sys.exit(1)

    return use_all


def print_git_command_hint(message: str) -> tuple[str, str]:
    """
    Show commit message and print a safe multi-line git commit command.

    Returns (summary_line, command_string).
    """
    raw_lines = message.splitlines()
    lines = [ln.rstrip() for ln in raw_lines if ln.strip()]

    print("\n--- Suggested commit message ---\n")
    print(message)
    print("\n--------------------------------")

    if not lines:
        print("\n(No non-empty summary line detected.)\n")
        return "", ""

    summary = lines[0].strip()
    body_lines = [ln for ln in lines[1:] if ln.strip()]

    escaped_summary = summary.replace('"', '\\"')

    cmd_lines = [f'git commit -m "{escaped_summary}"']

    for ln in body_lines:
        escaped = ln.replace('"', '\\"')
        cmd_lines.append(f'-m "{escaped}"')

    # Join with backslashes for nice multi-line shell formatting
    full_cmd = " \\\n  ".join(cmd_lines)

    print("\nCopyable multi-line command:")
    print(full_cmd)
    print()

    return summary, full_cmd


def interactive_menu(message: str) -> None:
    """Show message and allow: accept+clipboard, paraphrase, cancel."""
    current = message
    while True:
        _, cmd = print_git_command_hint(current)

        print(
            "[ai-commit] Choose an action:\n"
            "  1) Accept this message (copy command to clipboard)\n"
            "  2) Paraphrase / rewrite message\n"
            "  3) Cancel\n"
        )

        choice = input("Selection [1/2/3] (default: 1): ").strip()

        if choice in ("", "1"):
            if cmd:
                copy_to_clipboard(cmd)
                print(
                    "[ai-commit] Command printed above and copied (if clipboard tool was found).\n"
                    "            Paste it in your terminal to run the commit.",
                    file=sys.stderr,
                )
            else:
                print(
                    "[ai-commit] No valid summary line, nothing copied.",
                    file=sys.stderr,
                )
            return

        elif choice == "2":
            print("[ai-commit] rewriting message...\n")
            new_message = paraphrase_message(current)
            if not new_message or new_message == current:
                print("[ai-commit] rewrite resulted in no change.", file=sys.stderr)
            else:
                current = new_message
            # loop again with updated message

        else:
            print("[ai-commit] Cancelled.", file=sys.stderr)
            return


def main() -> None:
    use_all = parse_args(sys.argv[1:])
    diff = run_git_diff(use_all)
    system_prompt, user_prompt = build_prompt(diff)
    message = call_model(system_prompt, user_prompt)
    interactive_menu(message)


if __name__ == "__main__":
    main()
