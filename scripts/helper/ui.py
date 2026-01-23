# scripts/helper/ui.py
import os
from typing import ContextManager

# Shared formatting

def _env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip() == "1"

def _wants_verbose() -> bool:
    if _env_bool("VLM_QUIET", "0"):
        return False
    return _env_bool("VLM_VERBOSE", "1")

def _wants_rich() -> bool:
    return _env_bool("VLM_USE_RICH", "1")

class _PlainStatus:
    def __init__(self, ui: 'UI', msg: str):
        self.ui = ui
        self.msg = msg

    def __enter__(self):
        self.ui.log(self.msg)
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

class UI:
    def __init__(self, debug: bool = False):
        self.debug = debug
        self.verbose = _wants_verbose() or debug
        self._use_rich = _wants_rich()
        self._console = None
        self._Spinner = None

        if self._use_rich:
            try:
                from rich.console import Console  # type: ignore
                from rich.status import Status  # type: ignore
                self._console = Console()
                self._Spinner = Status
            except Exception:
                self._console = None
                self._Spinner = None

    def log(self, msg: str) -> None:
        if not self.verbose:
            return
        if self._console is not None:
            self._console.print(msg)
        else:
            print(msg)

    def warn(self, msg: str) -> None:
        if self._console is not None:
            self._console.print(f"[yellow]{msg}[/yellow]")
        else:
            print(msg)

    def err(self, msg: str) -> None:
        if self._console is not None:
            self._console.print(f"[red]{msg}[/red]")
        else:
            print(msg)

    def status(self, msg: str) -> ContextManager:
        if self._Spinner is not None and self._console is not None:
            return self._Spinner(msg, console=self._console)
        return _PlainStatus(self, msg)
