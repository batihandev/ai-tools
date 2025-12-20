# helper/spinner.py
import sys
import threading
import time
from typing import Callable, TypeVar

T = TypeVar("T")


def with_spinner(label: str, fn: Callable[[], T]) -> T:
    """Run fn() while showing a small spinner on stderr."""
    stop_flag = {"stop": False}

    def spinner():
        symbols = "|/-\\"
        idx = 0
        while not stop_flag["stop"]:
            sys.stderr.write(f"\r[{label}] " + symbols[idx % 4])
            sys.stderr.flush()
            idx += 1
            time.sleep(0.1)
        sys.stderr.write(f"\r[{label}] done   \n")
        sys.stderr.flush()

    thread = threading.Thread(target=spinner, daemon=True)
    thread.start()
    try:
        return fn()
    finally:
        stop_flag["stop"] = True
        thread.join()
