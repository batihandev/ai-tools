# scripts/helper/utils.py
from pathlib import Path

def atomic_write_text(path: Path, text: str) -> None:
    """
    Writes text to a file atomically by writing to a .tmp file first and then renaming.
    Example: path="foo.txt" -> writes "foo.txt.tmp" -> renames to "foo.txt".
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
