import subprocess
import sys
from .colors import Colors

def run_git_cmd(args: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
    """Executes a git command and returns the completed process object."""
    try:
        return subprocess.run(
            ["git", "-C", cwd] + args,
            capture_output=True,
            text=True,
            check=False 
        )
    except FileNotFoundError:
        # Fallback if git is not installed or weird system
        print(f"{Colors.r('Error: git not found in PATH')}", file=sys.stderr)
        sys.exit(1)

def git_stdout(args: list[str], cwd: str) -> str:
    res = run_git_cmd(args, cwd)
    if res.returncode != 0:
         # Depending on usage, we might want to raise or return empty.
         # For current ai_commit usage, empty string is often safer or handled by caller.
         # But strict failures like 'current_branch' check returncode.
         return ""
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
            # If nothing staged, try unstaged
            res = run_git_cmd(["diff"], cwd)

    if not res.stdout.strip():
        # Clean exit if absolutely no changes
        print(f"\n{Colors.r('✗ No changes detected in:')} {cwd}")
        sys.exit(0)
    return res.stdout
