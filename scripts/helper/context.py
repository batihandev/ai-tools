# helper/context.py
import os
import sys

# Single soft context limit for all local LLM tools.
# Override with LLM_SOFT_CONTEXT_LIMIT if you ever change models.
_SOFT_CONTEXT_LIMIT = int(os.getenv("LLM_SOFT_CONTEXT_LIMIT", "40000"))


def warn_if_approaching_context(label: str, text: str) -> None:
    """
    Print a warning if the given text is larger than the shared soft
    character limit for our local LLM.

    Args:
        label: Short tag for the tool, e.g. "ai_commit" or "investigate".
        text:  The input string that will be sent to the model.
    """
    length = len(text)
    if length > _SOFT_CONTEXT_LIMIT:
        print(
            f"[{label}] WARNING: input is {length} characters "
            f"(soft limit ~{_SOFT_CONTEXT_LIMIT}); model context may be tight.",
            file=sys.stderr,
        )
