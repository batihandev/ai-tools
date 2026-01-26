#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from dataclasses import dataclass
from textwrap import dedent
from typing import List, Optional

from pydantic import BaseModel, Field

# IMPORTANT: relative imports (works when imported as scripts.english_teacher)
from .helper.env import load_repo_dotenv
from .helper.omni_helper import OmniHelper
from .helper.spinner import with_spinner
from .helper.colors import Colors
from .helper.json_utils import safe_parse_model

load_repo_dotenv()


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------

DEFAULT_MODEL = os.getenv("ENGLISH_TEACHER_MODEL")
DEFAULT_NUM_CTX = int(os.getenv("ENGLISH_TEACHER_NUM_CTX", "4096"))
DEFAULT_TIMEOUT = int(os.getenv("ENGLISH_TEACHER_TIMEOUT", "60"))
DEFAULT_MODE = os.getenv("ENGLISH_TEACHER_MODE", "coach")  # coach|strict|correct

# Temperature for JSON tasks (lower = more deterministic)
DEFAULT_TEMPERATURE = 0.3
DEFAULT_TOP_P = 0.9


# -----------------------------------------------------------------------------
# Types (Pydantic Models)
# -----------------------------------------------------------------------------

class Mistake(BaseModel):
    frm: str
    to: str
    why: str


class Pronunciation(BaseModel):
    word: str
    ipa: str
    cue: str


class TeachOut(BaseModel):
    corrected_natural: str = ""
    corrected_literal: str = ""
    mistakes: List[Mistake] = Field(default_factory=list)
    pronunciation: List[Pronunciation] = Field(default_factory=list)
    reply: str = ""
    follow_up_question: str = ""
    raw_error: bool = False
    raw_output: str = ""
    audio_path: Optional[str] = None


@dataclass(frozen=True)
class TeachCfg:
    model: Optional[str] = DEFAULT_MODEL
    num_ctx: int = DEFAULT_NUM_CTX
    timeout: int = DEFAULT_TIMEOUT
    mode: str = DEFAULT_MODE
    temperature: float = DEFAULT_TEMPERATURE
    top_p: float = DEFAULT_TOP_P


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
          OR likely to be mispronounced by learners. Use standard IPA notation.
        - Use simple, intuitive pronunciation cues (e.g., "sounds like").

        If the user's text is unclear:
        - Make your best guess, but also ask a short clarifying question.

        If the user's English is already perfect:
        - Return empty lists for 'mistakes' and 'pronunciation'.
        - Provide a brief, encouraging reply.

        HARD CONSTRAINT:
        - Output MUST be strict, valid JSON.
        - No markdown, no code fences, no preambles, no trailing commentary.
        """
    ).strip()

    if mode == "strict":
        mode_block = dedent(
            """
            Mode: STRICT
            - Be thorough: include repeated or small mistakes if they matter.
            - Include pronunciation for any word that might be mispronounced.
            - Provide concise rule-of-thumb if helpful.
            """
        ).strip()
    elif mode == "correct":
        mode_block = dedent(
            """
            Mode: CORRECT ONLY
            - Do NOT continue the conversation or ask follow-up questions.
            - Provide corrections only (leave 'reply' and 'follow_up_question' empty).
            """
        ).strip()
    else:
        mode_block = dedent(
            """
            Mode: COACH
            - Continue the conversation naturally after corrections.
            - Keep it practical, friendly, and not overly formal.
            - Engage with follow-up questions.
            """
        ).strip()

    # One-shot example (golden output)
    example_input = "I has been working here for three years now and I love this job so much"
    example_output = {
        "corrected_natural": "I've been working here for three years now, and I love this job so much.",
        "corrected_literal": "I have been working here for three years, and I love this job very much.",
        "mistakes": [
            {
                "frm": "I has been",
                "to": "I have been",
                "why": "Subject-verb agreement: 'I' uses 'have', not 'has'."
            }
        ],
        "pronunciation": [
            {
                "word": "working",
                "ipa": "ˈwɜːrkɪŋ",
                "cue": "WER-king (with a soft 'r' sound at the start)"
            }
        ],
        "reply": "That's wonderful! Three years is a solid tenure. What aspect of the job brings you the most joy?",
        "follow_up_question": "What's your favorite project you've worked on here?"
    }

    example_section = dedent(
        f"""
        Example Input:
        "{example_input}"

        Example Output (valid JSON):
        {json.dumps(example_output, ensure_ascii=False, indent=2)}
        """
    ).strip()

    schema = dedent(
        """
        JSON Schema (exact keys required):
        {
          "corrected_natural": "string (how it sounds naturally)",
          "corrected_literal": "string (word-for-word correction)",
          "mistakes": [{"frm": "string", "to": "string", "why": "string"}],
          "pronunciation": [{"word": "string", "ipa": "string (IPA notation)", "cue": "string (intuitive cue)"}],
          "reply": "string (empty if mode is 'correct')",
          "follow_up_question": "string (empty if mode is 'correct')"
        }
        """
    ).strip()

    return f"{base}\n\n{mode_block}\n\n{example_section}\n\n{schema}"


def _build_user_prompt(text: str) -> str:
    return dedent(
        f"""
        User said (speech-to-text transcript):
        {text}

        Return strictly valid JSON matching the schema.
        """
    ).strip()


def _make_fallback_teachout(raw: str) -> TeachOut:
    """Create fallback TeachOut when parsing fails."""
    return TeachOut(
        corrected_natural="",
        corrected_literal="",
        mistakes=[],
        pronunciation=[],
        reply=raw,
        follow_up_question="",
        raw_error=True,
        raw_output=raw,
        audio_path=None,
    )


# -----------------------------------------------------------------------------
# Public API (importable)
# -----------------------------------------------------------------------------

def teach(
    text: str,
    mode: str = DEFAULT_MODE,
    cfg: Optional[TeachCfg] = None,
    session_id: Optional[str] = None,
) -> TeachOut:
    """
    Core function for FastAPI and CLI usage.

    Args:
        text: user utterance(s). You will likely pass combined transcripts.
        mode: coach|strict|correct
        cfg: optional configuration overrides (model/ctx/timeout/temperature/top_p).
        session_id: optional session ID for conversation memory across turns.
    """
    if cfg is None:
        cfg = TeachCfg(mode=mode)

    if mode not in ("coach", "strict", "correct"):
        mode = "coach"

    # Import helpers here to avoid circular imports
    from .helper.cache_helper import CorrectionCache
    from .helper.session_store import SessionStore

    # Check cache first (text corrections only, audio regenerated)
    cached = CorrectionCache.get(text, mode)
    if cached:
        # Regenerate audio for fresh tone variation
        out = cached.model_copy()
        
        # Generate fresh audio
        repo_root = Path(__file__).resolve().parents[1]
        public_audio_dir = repo_root / "frontend" / "public" / "audios"
        public_audio_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"{uuid.uuid4().hex}.wav"
        abs_audio_path = str(public_audio_dir / filename)
        rel_audio_path = f"/audios/{filename}"
        
        # Generate audio for the cached response
        audio_text = out.reply
        if out.follow_up_question:
            audio_text = f"{audio_text} {out.follow_up_question}"
        
        if audio_text.strip():
            try:
                OmniHelper.chat_with_audio(
                    text=audio_text,
                    output_audio_path=abs_audio_path,
                )
                out.audio_path = rel_audio_path
            except Exception:
                pass  # Continue without audio on failure
        
        # Update session if provided
        if session_id:
            SessionStore.add_exchange(session_id, text, out)
        
        return out

    # Get conversation history if session_id provided
    history = []
    if session_id:
        history = SessionStore.get_history(session_id, max_turns=3)

    system_prompt = _build_system_prompt(mode)
    user_prompt = _build_user_prompt(text)

    # Prepare audio output path
    repo_root = Path(__file__).resolve().parents[1]
    public_audio_dir = repo_root / "frontend" / "public" / "audios"
    public_audio_dir.mkdir(parents=True, exist_ok=True)
    
    filename = f"{uuid.uuid4().hex}.wav"
    abs_audio_path = str(public_audio_dir / filename)
    rel_audio_path = f"/audios/{filename}"
    
    try:
        # Use OmniHelper for unified LLM + TTS response
        # Note: Use 'persona' (prepended to user message) instead of system_prompt
        # because Qwen2.5-Omni requires a specific system prompt for TTS to work
        result = OmniHelper.chat_with_audio(
            text=f"{system_prompt}\n\n{user_prompt}",
            persona="English Teacher",
            output_audio_path=abs_audio_path,
            history=history,
        )
        raw = result["text"]
    except Exception as e:
        print(f"{Colors.r('Omni Error:')} {e}", file=sys.stderr)
        return _make_fallback_teachout(f"Error: {e}")
    
    out = safe_parse_model(raw, TeachOut, _make_fallback_teachout)
    
    # Set audio path if generated
    if result.get("audio_path"):
        out.audio_path = rel_audio_path

    # Cache the text correction (without audio)
    CorrectionCache.set(text, mode, out)

    # Update session history
    if session_id:
        SessionStore.add_exchange(session_id, text, out)
            
    return out


# -----------------------------------------------------------------------------
# CLI formatting with rich colors
# -----------------------------------------------------------------------------

def _format_cli(out: TeachOut) -> str:
    """
    Format TeachOut for CLI display with rich-compatible color codes.
    Uses ANSI colors that work in most terminals.
    """
    if out.raw_error:
        return (
            f"{Colors.r('✗ Error: model did not return valid JSON.')}\n\n"
            "Raw output:\n"
            + (out.raw_output or out.reply or "")
        )

    lines: List[str] = []

    # Header colors: 94=blue, 92=green, 91=red, 93=yellow
    lines.append(f"{Colors.b('► Corrected (natural):')} {out.corrected_natural.strip()}")
    lines.append(f"{Colors.b('► Corrected (literal):')}  {out.corrected_literal.strip()}")

    mistakes = out.mistakes or []
    if mistakes:
        lines.append("")
        lines.append(Colors.r("⚠ Mistakes:"))
        for m in mistakes:
            frm = (m.frm or "").strip()
            to = (m.to or "").strip()
            why = (m.why or "").strip()
            lines.append(f"  {Colors.r('✗')} {frm} → {Colors.g(to)}")
            lines.append(f"     {Colors.grey(f'({why})')}")

    pron = out.pronunciation or []
    if pron:
        lines.append("")
        lines.append(Colors.y("🔊 Pronunciation:"))
        for p in pron:
            word = (p.word or "").strip()
            ipa = (p.ipa or "").strip()
            cue = (p.cue or "").strip()
            ipa_part = f"/{ipa}/" if ipa else ""
            lines.append(f"  {word} {Colors.grey(ipa_part)}")
            lines.append(f"     → {cue}")

    reply = (out.reply or "").strip()
    if reply:
        lines.append("")
        lines.append(Colors.g("💬 Reply:"))
        lines.append(f"  {reply}")

    q = (out.follow_up_question or "").strip()
    if q:
        lines.append("")
        lines.append(Colors.g("❓ Follow-up:"))
        lines.append(f"  {q}")

    return "\n".join(lines).strip() + Colors.RESET


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
