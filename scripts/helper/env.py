from __future__ import annotations

from pathlib import Path

def load_repo_dotenv() -> None:
    """
    Load .env from repo root if present. No-op if missing.
    """
    try:
        from dotenv import load_dotenv
    except Exception:
        return

    repo_root = Path(__file__).resolve().parents[2]  # scripts/helper -> scripts -> repo
    env_path = repo_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)
