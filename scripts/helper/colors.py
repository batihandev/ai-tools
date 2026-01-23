# scripts/helper/colors.py
import sys
import os

class Colors:
    """
    Simple ANSI color helper.
    Docs: https://en.wikipedia.org/wiki/ANSI_escape_code
    """
    # Foreground
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    
    # Bright Foreground
    GREY = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

    # Styles
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"
    BLINK = "\033[5m"
    REVERSE = "\033[7m"
    HIDDEN = "\033[8m"

    @staticmethod
    def _wrap(text: str, color_code: str) -> str:
        if not sys.stdout.isatty() and os.getenv("FORCE_COLOR") != "1":
            return text
        return f"{color_code}{text}{Colors.RESET}"

    # Shortcuts for common colors
    @staticmethod
    def r(text: str) -> str: return Colors._wrap(text, Colors.BRIGHT_RED)
    @staticmethod
    def g(text: str) -> str: return Colors._wrap(text, Colors.BRIGHT_GREEN)
    @staticmethod
    def b(text: str) -> str: return Colors._wrap(text, Colors.BRIGHT_BLUE)
    @staticmethod
    def c(text: str) -> str: return Colors._wrap(text, Colors.BRIGHT_CYAN)
    @staticmethod
    def m(text: str) -> str: return Colors._wrap(text, Colors.BRIGHT_MAGENTA)
    @staticmethod
    def y(text: str) -> str: return Colors._wrap(text, Colors.BRIGHT_YELLOW)
    @staticmethod
    def w(text: str) -> str: return Colors._wrap(text, Colors.BRIGHT_WHITE)
    @staticmethod
    def grey(text: str) -> str: return Colors._wrap(text, Colors.GREY)

    # Styles
    @staticmethod
    def bold(text: str) -> str: return Colors._wrap(text, Colors.BOLD)
    @staticmethod
    def dim(text: str) -> str: return Colors._wrap(text, Colors.DIM)
