# helper/clipboard.py
import subprocess
import sys
from typing import Optional, Tuple


def copy_to_clipboard(text: str) -> Tuple[bool, Optional[str]]:
    """
    Best-effort clipboard copy.

    Tries, in order:
      - wl-copy (Wayland)
      - xclip (X11)
      - xsel (X11)
      - pbcopy (macOS)
      - clip.exe (WSL / Windows)

    Returns:
      (success, backend_name_or_None)
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
                # generic, tool-agnostic message
                print(
                    f"[clipboard] Copied to system clipboard via {label}.",
                    file=sys.stderr,
                )
                return True, label
        except FileNotFoundError:
            continue
        except Exception:
            continue

    print(
        "[clipboard] Could not copy to clipboard "
        "(no wl-copy/xclip/xsel/pbcopy/clip.exe found).",
        file=sys.stderr,
    )
    return False, None
