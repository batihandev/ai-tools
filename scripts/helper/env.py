from __future__ import annotations

import os
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


def env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip() == "1"


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default
