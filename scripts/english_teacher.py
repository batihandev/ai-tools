#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from textwrap import dedent
from typing import List, Optional, TypedDict

# IMPORTANT: relative imports (works when imported as scripts.english_teacher)
from .helper.env import load_repo_dotenv
from .helper.llm import ollama_chat, strip_fences_and_quotes
from .helper.spinner import with_spinner

load_repo_dotenv()


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------

DEFAULT_MODEL = os.getenv(
    "ENGLISH_TEACHER_MODEL",
    os.getenv("INVESTIGATE_MODEL", "llama3.1:8b"),
)
DEFAULT_NUM_CTX = int(os.getenv("ENGLISH_TEACHER_NUM_CTX", "4096"))
DEFAULT_TIMEOUT = int(os.getenv("ENGLISH_TEACHER_TIMEOUT", "60"))
DEFAULT_MODE = os.getenv("ENGLISH_TEACHER_MODE", "coach")  # coach|strict|correct


# -----------------------------------------------------------------------------
# Types
# -----------------------------------------------------------------------------

class Mistake(TypedDict):
    frm: str
    to: str
    why: str


class Pronunciation(TypedDict):
    word: str
    ipa: str
    cue: str


class TeachOut(TypedDict, total=False):
    corrected_natural: str
    corrected_literal: str
    mistakes: List[Mistake]
    pronunciation: List[Pronunciation]
    reply: str
    follow_up_question: str
    raw_error: bool
    raw_output: str


@dataclass(frozen=True)
class TeachCfg:
    model: str = DEFAULT_MODEL
    num_ctx: int = DEFAULT_NUM_CTX
    timeout: int = DEFAULT_TIMEOUT
    mode: str = DEFAULT_MODE


# -----------------------------------------------------------------------------
# Prompting
# -----------------------------------------------------------------------------

def _build_system_prompt(mode: str) -> str:
    base = dedent(
        """
        You are an English conversation coach for a non-native speaker.

        Important context:
        - The user's input is produced by a speech-to-text system.
        - Treat punctuation and casing as unreliable artifacts of transcription.
        - Focus on spoken English: wording, grammar, clarity, and natural phrasing.
        - Do not nitpick punctuation/capitalization unless it changes the meaning.

        Goals:
        - Preserve the user's intended meaning.
        - Correct grammar and wording with minimal changes.
        - Highlight only the most important mistakes (avoid overwhelming the user).
        - Provide pronunciation tips for words that are commonly mispronounced
          OR likely to be mispronounced by learners.

        If the user's text is unclear:
        - Make your best guess, but also ask a short clarifying question.

        HARD CONSTRAINT:
        - Output MUST be strict JSON.
        - No markdown, no code fences, no preambles, no trailing commentary.
        """
    ).strip()

    if mode == "strict":
        mode_block = dedent(
            """
            Mode: STRICT
            - Be more thorough: include repeated or small mistakes if they matter.
            - Include 1 short rule-of-thumb if helpful.
            """
        ).strip()
    elif mode == "correct":
        mode_block = dedent(
            """
            Mode: CORRECT ONLY
            - Do NOT continue the conversation.
            - Provide corrections only (reply must be empty).
            """
        ).strip()
    else:
        mode_block = dedent(
            """
            Mode: COACH
            - Continue the conversation naturally after corrections.
            - Keep it practical and not overly formal.
            """
        ).strip()

    schema = dedent(
        """
        JSON Schema (exact keys):
        {
          "corrected_natural": "string",
          "corrected_literal": "string",
          "mistakes": [{"frm": "string", "to": "string", "why": "string"}],
          "pronunciation": [{"word": "string", "ipa": "string", "cue": "string"}],
          "reply": "string (empty if mode is 'correct')",
          "follow_up_question": "string"
        }
        """
    ).strip()

    return f"{base}\n\n{mode_block}\n\n{schema}"


def _build_user_prompt(text: str) -> str:
    return dedent(
        f"""
        User said (speech-to-text transcript):
        {text}

        Return strictly valid JSON matching the schema.
        """
    ).strip()


def _safe_parse_json(raw: str) -> TeachOut:
    cleaned = strip_fences_and_quotes(raw).strip()
    try:
        obj = json.loads(cleaned)
        if not isinstance(obj, dict):
            raise ValueError("JSON root is not an object")
        return obj  # type: ignore[return-value]
    except Exception:
        # Preserve raw output for debugging; do not throw for API robustness.
        return TeachOut(
            corrected_natural="",
            corrected_literal="",
            mistakes=[],
            pronunciation=[],
            reply=cleaned,
            follow_up_question="",
            raw_error=True,
            raw_output=cleaned,
        )


# -----------------------------------------------------------------------------
# Public API (importable)
# -----------------------------------------------------------------------------

def teach(text: str, mode: str = DEFAULT_MODE, cfg: Optional[TeachCfg] = None) -> TeachOut:
    """
    Core function for FastAPI usage.

    Args:
        text: user utterance(s). You will likely pass combined transcripts.
        mode: coach|strict|correct
        cfg: optional configuration overrides (model/ctx/timeout).
    """
    if cfg is None:
        cfg = TeachCfg(mode=mode)

    if mode not in ("coach", "strict", "correct"):
        mode = "coach"

    system_prompt = _build_system_prompt(mode)
    user_prompt = _build_user_prompt(text)

    raw = ollama_chat(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=cfg.model,
        num_ctx=cfg.num_ctx,
        timeout=cfg.timeout,
    )
    return _safe_parse_json(raw)


# -----------------------------------------------------------------------------
# CLI formatting
# -----------------------------------------------------------------------------

def _format_cli(out: TeachOut) -> str:
    if out.get("raw_error"):
        return (
            "Error: model did not return valid JSON.\n\nRaw output:\n"
            + (out.get("raw_output") or out.get("reply") or "")
        )

    lines: List[str] = []
    lines.append(f"Corrected (natural): {out.get('corrected_natural', '').strip()}")
    lines.append(f"Corrected (literal):  {out.get('corrected_literal', '').strip()}")

    mistakes = out.get("mistakes") or []
    if mistakes:
        lines.append("")
        lines.append("Mistakes:")
        for m in mistakes:
            frm = (m.get("frm") or "").strip()
            to = (m.get("to") or "").strip()
            why = (m.get("why") or "").strip()
            lines.append(f"- {frm} -> {to} ({why})")

    pron = out.get("pronunciation") or []
    if pron:
        lines.append("")
        lines.append("Pronunciation:")
        for p in pron:
            word = (p.get("word") or "").strip()
            ipa = (p.get("ipa") or "").strip()
            cue = (p.get("cue") or "").strip()
            ipa_part = f"/{ipa}/" if ipa else ""
            lines.append(f"- {word} {ipa_part} — {cue}".strip())

    reply = (out.get("reply") or "").strip()
    if reply:
        lines.append("")
        lines.append("Reply:")
        lines.append(reply)

    q = (out.get("follow_up_question") or "").strip()
    if q:
        lines.append("")
        lines.append("Follow-up question:")
        lines.append(q)

    return "\n".join(lines).strip() + "\n"


def _print_help() -> None:
    print(
        dedent(
            """
            english-teacher — English conversation coach (LLM-powered)

            Usage:
              english-teacher [--mode coach|strict|correct] [--json] [TEXT...]
              echo "your text" | english-teacher --mode coach
              python -m scripts.english_teacher --mode coach "hello i am fine"

            Notes:
              - For best reliability, run as module (python -m scripts.english_teacher)
                or use your generated wrapper.
              - API usage: from scripts.english_teacher import teach
            """
        ).strip()
    )


def _parse_args(argv: List[str]) -> tuple[str, Optional[str], bool]:
    mode = DEFAULT_MODE
    json_out = False
    parts: List[str] = []

    i = 0
    while i < len(argv):
        a = argv[i]

        if a in ("-h", "--help", "help"):
            _print_help()
            sys.exit(0)

        if a == "--mode":
            if i + 1 >= len(argv):
                print("english-teacher: --mode requires a value", file=sys.stderr)
                sys.exit(1)
            mode = argv[i + 1]
            i += 2
            continue

        if a == "--json":
            json_out = True
            i += 1
            continue

        if a.startswith("-"):
            print(f"english-teacher: unknown option: {a}", file=sys.stderr)
            _print_help()
            sys.exit(1)

        parts.append(a)
        i += 1

    text: Optional[str] = None
    if not sys.stdin.isatty():
        text = sys.stdin.read().strip()
    elif parts:
        text = " ".join(parts).strip()

    return mode, text, json_out


def main() -> None:
    mode, text, json_out = _parse_args(sys.argv[1:])

    if not text:
        print("english-teacher: no input text. Pipe text or pass it as args.", file=sys.stderr)
        _print_help()
        sys.exit(1)

    def _run() -> TeachOut:
        return teach(text, mode=mode)

    if sys.stdout.isatty() and not json_out:
        out = with_spinner("english-teacher", _run)
    else:
        out = _run()

    if json_out:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(_format_cli(out), end="")


if __name__ == "__main__":
    main()
