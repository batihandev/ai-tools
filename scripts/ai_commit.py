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
from .helper.json_utils import safe_parse_model
from .helper.git import (
    run_git_cmd,
    push_with_upstream_if_needed,
    get_git_diff,
)

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
        description="A short imperative summary line (< 50 chars preferred).",
    )
    bullets: List[CommitFile] = Field(default_factory=list)
    
    # Fallback for display if something goes wrong but we have partial data
    raw_output: str = ""
    is_error: bool = False

@dataclass(frozen=True)
class CommitCfg:
    model: str = os.getenv("AI_COMMIT_MODEL", "llama3.1:8b")
    num_ctx: int = 8192
    timeout: int = 120
    temperature: float = 0.2
    cwd: str = os.environ.get("USER_PWD", os.getcwd())

# -----------------------------------------------------------------------------
# LLM Execution
# -----------------------------------------------------------------------------

def generate_commit(diff: str, cfg: CommitCfg) -> CommitData:
    system = dedent("""
        You are an expert developer writing git commit messages.
        
        Rules:
        1. "summary": strictly < 72 chars, imperative mood (e.g., "Add feature" not "Added feature").
        2. "bullets": list of changed files with brief explanations.
        3. Output MUST be valid JSON.
        
        Schema:
        {
          "summary": "string",
          "bullets": [
            { "path": "string", "explanation": "string" }
          ]
        }
    """).strip()

    try:
        raw = ollama_chat(
            system_prompt=system,
            user_prompt=f"Generate commit for this diff:\n{diff}",
            model=cfg.model,
            num_ctx=cfg.num_ctx,
            timeout=cfg.timeout,
            temperature=cfg.temperature,
        )
    except Exception as e:
        return CommitData(summary="Error generating commit", bullets=[], raw_output=str(e), is_error=True)

    return safe_parse_model(raw, CommitData, lambda r: CommitData(summary="Failed to parse JSON", bullets=[], raw_output=r, is_error=True))

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
        
        if commit_data.is_error:
            print(f"\n{Colors.r('✗ LLM Error:')}\n{commit_data.raw_output}")
            # Offer retry
            if input(f"\n{Colors.m('Retry? [y/N]:')} ").lower().strip() == 'y':
                continue
            sys.exit(1)

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
