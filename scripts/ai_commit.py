#!/usr/bin/env python3
"""
ai_commit – suggest git commit messages using local LLM.
Supports auto-staging, direct commit, and pushing to origin.
"""
from __future__ import annotations

import os
import sys
import subprocess
import json
import re
from dataclasses import dataclass
from textwrap import dedent
from typing import List, Optional

from pydantic import BaseModel, Field, AliasChoices

# Relative imports
from .helper.env import load_repo_dotenv
from .helper.llm import ollama_chat, strip_fences_and_quotes
from .helper.spinner import with_spinner
from .helper.clipboard import copy_to_clipboard

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
        description="A short imperative summary line"
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

def run_git_cmd(args: list[str], cwd: str):
    """Executes a git command and returns the completed process object."""
    return subprocess.run(
        ["git", "-C", cwd] + args,
        capture_output=True,
        text=True
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
        print(f"\n\033[91m✗ No changes detected in: {cwd}\033[0m")
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
        temperature=cfg.temperature
    )
    
    cleaned = strip_fences_and_quotes(raw).strip()
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
    
    diff = get_git_diff(use_all, cfg.cwd)
    
    commit_data = with_spinner(
        "\033[96mai_commit analyzing changes\033[0m", 
        lambda: generate_commit(diff, cfg)
    )

    # Prepare Commit Arguments
    summary_esc = commit_data.summary.replace('"', '\\"')
    git_args = ["commit", "-m", summary_esc]
    for b in commit_data.bullets:
        bullet_text = f"- {b.path}: {b.explanation}".replace('"', '\\"')
        git_args += ["-m", bullet_text]

    # Visual Presentation
    print(f"\n\033[94m► Proposed Summary:\033[0m \033[1m{commit_data.summary}\033[0m")
    for b in commit_data.bullets:
        print(f"  \033[90m•\033[0m \033[32m{b.path}\033[0m: {b.explanation}")
    
    # Construct multi-line command for display
    cmd_display = "git commit"
    cmd_display += f' -m "{summary_esc}"'
    for b in commit_data.bullets:
        cmd_display += f' \\\n  -m "- {b.path}: {b.explanation}"'
    
    print(f"\n\033[93m► Generated Command:\033[0m\n{cmd_display}\n")

    print(f"\033[95m[ai_commit]\033[0m Select action:")
    print("  \033[94m1)\033[0m Copy command to clipboard")
    print("  \033[94m2)\033[0m Commit locally now")
    print("  \033[94m3)\033[0m Commit and Push to origin")
    print("  \033[94m4)\033[0m Cancel")

    try:
        choice = input(f"\n\033[95mSelection [1-4] (default 1):\033[0m ").strip()
    except KeyboardInterrupt:
        print("\n\033[90mCancelled.\033[0m")
        sys.exit(0)

    if choice in ("2", "3"):
        # Auto-staging check
        staged_check = run_git_cmd(["diff", "--cached", "--name-only"], cfg.cwd)
        if not staged_check.stdout.strip():
            print("\033[90mNo staged changes found. Auto-staging all changes...\033[0m")
            subprocess.run(["git", "-C", cfg.cwd, "add", "."], check=True)

        # Run Commit
        subprocess.run(["git", "-C", cfg.cwd] + git_args, check=True)
        print("\033[92m✓ Committed successfully.\033[0m")

        if choice == "3":
            print("\033[94mPushing to origin...\033[0m")
            subprocess.run(["git", "-C", cfg.cwd, "push"], check=True)
            print("\033[92m✓ Pushed successfully.\033[0m")

    elif choice in ("", "1"):
        # Copy to clipboard
        success, backend = copy_to_clipboard(cmd_display.replace(" \\\n  ", " "))
        if success:
            print(f"\033[92m✓ Copied to clipboard via {backend}.\033[0m")
    else:
        print("\033[90mOperation cancelled.\033[0m")

if __name__ == "__main__":
    main()