#!/usr/bin/env python3
"""
ai_commit – suggest git commit messages using local LLM.
Supports auto-staging, direct commit, pushing to origin, and regeneration.
"""
from __future__ import annotations

import os
import sys
import subprocess
import re
from dataclasses import dataclass
from textwrap import dedent
from typing import List

from pydantic import BaseModel, Field, AliasChoices

# Relative imports
from .helper.env import load_repo_dotenv
from .helper.llm import ollama_chat
from .helper.spinner import with_spinner
from .helper.clipboard import copy_to_clipboard
from .helper.colors import Colors
from .helper.json_utils import strip_json_fence

load_repo_dotenv()

# -----------------------------------------------------------------------------
# Config & Types
# -----------------------------------------------------------------------------

class CommitFile(BaseModel):
    path: str
    explanation: str

class CommitData(BaseModel):
    summary: str = Field(
        validation_alias=AliasChoices("summary", "title", "header", "headline"),
        description="A short imperative summary line",
    )
    bullets: List[CommitFile] = Field(default_factory=list)

@dataclass(frozen=True)
class CommitCfg:
    model: str = os.getenv("AI_COMMIT_MODEL", "llama3.1:8b")
    num_ctx: int = 8192
    timeout: int = 120
    temperature: float = 0.2
    cwd: str = os.environ.get("USER_PWD", os.getcwd())

# -----------------------------------------------------------------------------
# Git Helpers
# -----------------------------------------------------------------------------

def run_git_cmd(args: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
    """Executes a git command and returns the completed process object."""
    return subprocess.run(
        ["git", "-C", cwd] + args,
        capture_output=True,
        text=True,
    )

def git_stdout(args: list[str], cwd: str) -> str:
    res = run_git_cmd(args, cwd)
    return (res.stdout or "").strip()

def current_branch(cwd: str) -> str:
    name = git_stdout(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    if not name or name == "HEAD":
        raise RuntimeError("Not on a branch (detached HEAD). Cannot set upstream.")
    return name

def has_upstream(cwd: str) -> bool:
    # exits non-zero if no upstream is configured
    res = run_git_cmd(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], cwd)
    return res.returncode == 0

def push_with_upstream_if_needed(cwd: str) -> None:
    """
    Pushes to origin. If the current branch has no upstream, sets it to origin/<branch>.
    """
    if has_upstream(cwd):
        subprocess.run(["git", "-C", cwd, "push"], check=True)
        return

    branch = current_branch(cwd)
    subprocess.run(
        ["git", "-C", cwd, "push", "--set-upstream", "origin", branch],
        check=True,
    )

def get_git_diff(use_all: bool, cwd: str) -> str:
    """Retrieves diff text, falling back from staged to unstaged if needed."""
    if use_all:
        res = run_git_cmd(["diff", "HEAD"], cwd)
    else:
        res = run_git_cmd(["diff", "--cached"], cwd)
        if not res.stdout.strip():
            res = run_git_cmd(["diff"], cwd)

    if not res.stdout.strip():
        print(f"\n{Colors.r('✗ No changes detected in:')} {cwd}")
        sys.exit(0)
    return res.stdout

# -----------------------------------------------------------------------------
# LLM Execution
# -----------------------------------------------------------------------------

def generate_commit(diff: str, cfg: CommitCfg) -> CommitData:
    system = dedent("""
        You write git commits in JSON.
        Keys: "summary" (string, <72 chars), "bullets" (list of {path, explanation}).
        Focus on 'what' and 'why'. Return ONLY JSON.
    """).strip()

    raw = ollama_chat(
        system_prompt=system,
        user_prompt=f"Generate commit for this diff:\n{diff}",
        model=cfg.model,
        num_ctx=cfg.num_ctx,
        timeout=cfg.timeout,
        temperature=cfg.temperature,
    )

    cleaned = strip_json_fence(raw).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON found in LLM output: {cleaned}")

    return CommitData.model_validate_json(match.group(0))

# -----------------------------------------------------------------------------
# Main Execution Flow
# -----------------------------------------------------------------------------

def main() -> None:
    cfg = CommitCfg()
    use_all = "--all" in sys.argv

    # 1. Capture Diff once
    diff = get_git_diff(use_all, cfg.cwd)

    while True:
        # 2. Generate Commit Message
        commit_data = with_spinner(
            Colors.c("ai_commit analyzing changes"),
            lambda: generate_commit(diff, cfg),
        )

        # 3. Prepare Commit Arguments
        summary_esc = commit_data.summary.replace('"', '\\"')
        git_args = ["commit", "-m", summary_esc]
        for b in commit_data.bullets:
            bullet_text = f"- {b.path}: {b.explanation}".replace('"', '\\"')
            git_args += ["-m", bullet_text]

        # 4. Visual Presentation
        print(f"\n{Colors.b('► Proposed Summary:')} {Colors.bold(commit_data.summary)}")
        for b in commit_data.bullets:
            print(f"  {Colors.grey('•')} {Colors.g(b.path)}: {b.explanation}")

        cmd_display = "git commit"
        cmd_display += f' -m "{summary_esc}"'
        for b in commit_data.bullets:
            cmd_display += f' \\\n  -m "- {b.path}: {b.explanation}"'

        print(f"\n{Colors.y('► Generated Command:')}\n{cmd_display}\n")

        # 5. Menu
        print(f"{Colors.m('[ai_commit]')} Select action:")
        print(f"  {Colors.b('1)')} Copy command to clipboard")
        print(f"  {Colors.b('2)')} Commit locally now")
        print(f"  {Colors.b('3)')} Commit and Push to origin")
        print(f"  {Colors.b('4)')} Paraphrase Summary (Short Retry)")
        print(f"  {Colors.b('5)')} Full Retry (Regenerate from diff)")
        print(f"  {Colors.b('6)')} Cancel")

        try:
            choice = input(f"\n{Colors.m('Selection [1-6] (default 1):')} ").strip()
        except KeyboardInterrupt:
            print(f"\n{Colors.grey('Cancelled.')}")
            sys.exit(0)

        # 6. Action Handling
        if choice == "5":
            print(Colors.grey("Regenerating..."))
            continue  # Re-enters the loop to call LLM again

        if choice == "4":
            # Slight tweak: you currently just re-run; kept as-is.
            print(Colors.grey("Retrying with variety..."))
            continue

        if choice in ("2", "3"):
            staged_check = run_git_cmd(["diff", "--cached", "--name-only"], cfg.cwd)
            if not staged_check.stdout.strip():
                print(Colors.grey("No staged changes found. Auto-staging all changes..."))
                subprocess.run(["git", "-C", cfg.cwd, "add", "."], check=True)

            subprocess.run(["git", "-C", cfg.cwd] + git_args, check=True)
            print(Colors.g("✓ Committed successfully."))

            if choice == "3":
                print(Colors.b("Pushing to origin..."))
                push_with_upstream_if_needed(cfg.cwd)
                print(Colors.g("✓ Pushed successfully."))
            break  # Exit loop after successful commit

        elif choice in ("", "1"):
            success, backend = copy_to_clipboard(cmd_display.replace(" \\\n  ", " "))
            if success:
                print(Colors.g(f"✓ Copied to clipboard via {backend}."))
            break  # Exit loop after copy

        elif choice == "6":
            print(Colors.grey("Operation cancelled."))
            break

        else:
            print(Colors.r("Invalid selection."))
            continue

if __name__ == "__main__":
    main()
