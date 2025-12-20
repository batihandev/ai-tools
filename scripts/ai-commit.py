#!/usr/bin/env python3
import sys
import subprocess
from textwrap import dedent

from helper.spinner import with_spinner
from helper.llm import ollama_chat, strip_fences_and_quotes
from helper.clipboard import copy_to_clipboard
from helper.context import warn_if_approaching_context

"""
ai-commit – suggest git commit messages using local LLM (Llama 3.1:8b).

USAGE

  # 1) Default: use staged changes (git diff --cached), interactive menu
  ai-commit

  # 2) Use unstaged working tree changes instead (git diff)
  ai-commit --all
"""


# ---------------------------------------------------------------------------
# Git diff helpers
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

    warn_if_approaching_context("ai-commit", diff)

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


def extract_changed_files(diff: str) -> list[str]:
    """
    Extract paths of files that are changed in this diff.

    We look at lines like:
      diff --git a/path b/path

    We take the "b/..." side as the file path, for all changes
    (added, modified, renamed, deleted).
    """
    changed = set()

    for line in diff.splitlines():
        if line.startswith("diff --git"):
            parts = line.split()
            if len(parts) >= 4:
                b_part = parts[3]  # e.g., "b/scripts/ai-commit.py"
                path = b_part[2:] if b_part.startswith("b/") else b_part
                changed.add(path)

    return sorted(changed)


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def build_prompt(diff: str, changed_files: list[str]) -> tuple[str, str]:
    limit = estimate_summary_limit(diff)

    if limit is not None:
        summary_req = (
            f"- Line 1 must be a short imperative summary (ideally <= {limit} characters).\n"
        )
    else:
        summary_req = "- Line 1 must be a concise imperative summary.\n"

    if changed_files:
        files_list = "\n".join(f"    - {path}" for path in changed_files)
        files_hint = (
            "Changed files in this diff:\n"
            f"{files_list}\n"
            "- After the blank line, write at least one bullet line for EACH path above.\n"
            "- Bullet format (exact):\n"
            "      - path/to/file.ext: very short purpose/role\n"
            "- Use appropriate verbs for each file, e.g.:\n"
            "      Add/Introduce/Create for new code\n"
            "      Fix/Update/Refactor for modifications\n"
            "      Remove/Delete/Drop for deletions\n"
        )
    else:
        files_hint = ""

    system_prompt = dedent(
        f"""
        You write git commit messages.

        Requirements:
        {summary_req}{files_hint}
        - Use present tense, imperative style (e.g., "Add script for X", "Fix bug in Y").
        - Focus on what changed and why, not how.
        - Treat the input as a unified git diff.
        - Do NOT mention these instructions, the diff, or that this is a generated message.

        Output format:
        1) Line 1: summary (one line).
        2) Line 2: blank.
        3) Then bullet lines in the form:
               - path/to/file.ext: short purpose
           with at least one bullet for each changed file.
        4) Optional extra bullets AFTER that are allowed.

        Output rules:
        - Return ONLY the commit message text.
        - No explanations, headings, or commentary.
        - No backticks or code fences.
        """
    ).strip()

    if changed_files:
        files_for_user = "\n".join(f"- {p}" for p in changed_files)
        files_section = (
            "Changed files (each must have at least one bullet after the blank line):\n"
            f"{files_for_user}\n\n"
        )
    else:
        files_section = ""

    user_prompt = (
        "Generate a git commit message for the following git diff.\n\n"
        f"{files_section}"
        "Format reminder: summary line, blank line, then '- path: purpose' bullets.\n\n"
        "Here is the diff:\n"
        "```diff\n"
        f"{diff}\n"
        "```"
    )

    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# Second-pass LLM sanitizer + bullet enforcement
# ---------------------------------------------------------------------------


def clean_commit_message_llm(text: str) -> str:
    """
    Second LLM pass that ONLY removes meta/self-referential lines and
    cleans spacing. No local heuristic sanitizer.
    """
    raw_msg = strip_fences_and_quotes(text)

    system_prompt = dedent(
        """
        You are a git commit message sanitizer.

        Input:
        - A full commit message (summary + body).

        Allowed actions:
        - Delete lines that are meta or self-referential, e.g.:
          * mention "this commit message", "required format", "instruction", "generated".
        - Delete notes that only explain what you changed or how you cleaned the message.
        - Remove blank lines at the start or end.
        - Collapse multiple consecutive blank lines into a single one.

        Forbidden:
        - Do not rewrite or paraphrase any remaining lines.
        - Do not add new content.
        - Do not wrap the result in backticks or code fences.
        - Do not add any commentary about the cleaning step.

        Output:
        - Only the cleaned commit message text.
        - No explanations or extra text about the cleaning step.
        """
    ).strip()

    user_prompt = (
        "Clean this commit message by ONLY deleting meta/self-referential lines "
        "and normalizing blank lines. Do not rewrite the remaining lines:\n\n"
        f"{raw_msg}"
    )

    cleaned_raw = ollama_chat(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        num_ctx=2048,
        timeout=60,
    )
    return strip_fences_and_quotes(cleaned_raw)


def ensure_bullets_for_files(message: str, changed_files: list[str]) -> str:
    """
    Ensure there is at least one bullet line mentioning each changed file.

    If the model skipped a file, append a minimal bullet at the end:
      - path: update
    """
    if not changed_files:
        return message

    lines = message.splitlines()

    # Find body start (first blank line after summary)
    body_start = 0
    if lines:
        for idx, ln in enumerate(lines):
            if idx == 0:
                continue  # summary
            if not ln.strip():
                body_start = idx + 1
                break
        else:
            body_start = 1  # no blank line; treat everything after summary as body

    body_lines = lines[body_start:]
    present_paths: set[str] = set()

    for ln in body_lines:
        stripped = ln.lstrip()
        if not stripped.startswith(("-", "*")):
            continue
        for path in changed_files:
            if path in stripped:
                present_paths.add(path)

    missing = [p for p in changed_files if p not in present_paths]
    if not missing:
        return message

    out_lines = lines[:]
    if out_lines and out_lines[-1].strip():
        out_lines.append("")  # ensure a blank line before auto bullets

    for path in missing:
        out_lines.append(f"- {path}: update")

    return "\n".join(out_lines)


def call_model(system_prompt: str, user_prompt: str, changed_files: list[str]) -> str:
    """
    Call local Ollama to generate the commit message, then:
      1) run LLM sanitizer
      2) enforce at least one bullet per changed file
    """
    def _call():
        raw = ollama_chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            num_ctx=16000,
            timeout=180,
        )
        cleaned = clean_commit_message_llm(raw)
        final = ensure_bullets_for_files(cleaned, changed_files)
        return final

    try:
        return with_spinner("ai-commit generating", _call)
    except Exception as e:
        print(f"[ai-commit] Error calling Ollama: {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Paraphrasing (summary-only, from current base generation)
# ---------------------------------------------------------------------------


def paraphrase_message(base_message: str) -> str:
    """
    Paraphrase ONLY the first line (summary) of the given base message.

    - The body/bullets are kept EXACTLY as in base_message.
    - Caller controls what "base_message" is (e.g., initial or retried generation),
      so we never paraphrase a paraphrase unless the caller chooses to.
    """
    lines = base_message.splitlines()
    if not lines:
        return base_message

    summary = lines[0].strip()
    body = "\n".join(lines[1:])

    if not summary:
        return base_message

    system_prompt = dedent(
        """
        You are a git commit summary rewriter.

        Rewrite the provided ONE-LINE commit summary:
        - Keep the same meaning and intent.
        - Use imperative, present tense.
        - Keep it concise but clear.

        Constraints:
        - Output MUST be a single line (no newlines).
        - Do NOT add quotes or backticks.
        - Do NOT mention that you are rewriting or paraphrasing.
        """
    ).strip()

    user_prompt = f"Rewrite this commit summary line:\n\n{summary}\n"

    try:
        raw = ollama_chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            num_ctx=1024,
            timeout=60,
        )
        cleaned = strip_fences_and_quotes(raw).strip()
        new_summary = cleaned.splitlines()[0].strip() if cleaned else summary
        if not new_summary:
            new_summary = summary
    except Exception as e:
        print(f"[ai-commit] Paraphrase failed, keeping original summary: {e}", file=sys.stderr)
        return base_message

    if body:
        return new_summary + "\n" + body
    return new_summary


# ---------------------------------------------------------------------------
# Clipboard helper (thin wrapper around generic helper.clipboard)
# ---------------------------------------------------------------------------


def copy_commit_command_to_clipboard(command: str) -> bool:
    """
    Copy the git commit command to the clipboard using the shared helper.

    Returns:
      True if copied, False otherwise.
    """
    success, backend = copy_to_clipboard(command)
    if success:
        print(
            f"[ai-commit] Commit command copied to clipboard via {backend}.",
            file=sys.stderr,
        )
    else:
        print(
            "[ai-commit] Could not copy commit command to clipboard.",
            file=sys.stderr,
        )
    return success


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

    full_cmd = " \\\n  ".join(cmd_lines)

    print("\nCopyable multi-line command:")
    print(full_cmd)
    print()

    return summary, full_cmd


def interactive_menu(
    initial_message: str,
    system_prompt: str,
    user_prompt: str,
    changed_files: list[str],
) -> None:
    """
    Show message and allow: accept+clipboard, paraphrase, retry, cancel.

    - We keep a "base_message" which is the latest raw generation from the model.
    - Paraphrase always works from the current base_message (summary-only).
    - Retry regenerates a new base_message via call_model, without redoing git diff.
    """
    base_message = initial_message
    current = initial_message

    while True:
        _, cmd = print_git_command_hint(current)

        print(
            "[ai-commit] Choose an action:\n"
            "  1) Accept this message (copy command to clipboard)\n"
            "  2) Paraphrase / rewrite SUMMARY line\n"
            "  3) Retry generation (new commit message)\n"
            "  4) Cancel\n"
        )

        choice = input("Selection [1/2/3/4] (default: 1): ").strip()

        if choice in ("", "1"):
            if cmd:
                copy_commit_command_to_clipboard(cmd)
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
            print("[ai-commit] rewriting SUMMARY line...\n")
            new_message = paraphrase_message(base_message)
            if not new_message or new_message == current:
                print("[ai-commit] rewrite resulted in no visible change.", file=sys.stderr)
            else:
                current = new_message

        elif choice == "3":
            print("[ai-commit] regenerating commit message...\n", file=sys.stderr)
            # New base from the same diff & prompts, no extra git work.
            base_message = call_model(system_prompt, user_prompt, changed_files)
            current = base_message

        else:
            print("[ai-commit] Cancelled.", file=sys.stderr)
            return


def main() -> None:
    use_all = parse_args(sys.argv[1:])
    diff = run_git_diff(use_all)
    changed_files = extract_changed_files(diff)
    system_prompt, user_prompt = build_prompt(diff, changed_files)
    message = call_model(system_prompt, user_prompt, changed_files)
    interactive_menu(message, system_prompt, user_prompt, changed_files)


if __name__ == "__main__":
    main()
