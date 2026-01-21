# AI Coding Agent Instructions

## Project Overview

**ai-scripts** is a hybrid Python + React/TypeScript project providing local AI-powered CLI tools and a web UI for voice transcription, English coaching, and code analysis. All AI runs locally via Ollama (no cloud APIs).

### Architecture

- **Backend**: FastAPI server (`server/app/`) with PostgreSQL persistence; handles audio transcription, English teacher responses, chat state
- **Frontend**: React 19 + Vite + Tailwind (`frontend/src/`); real-time voice capture with silence detection
- **CLI Tools**: Standalone Python scripts in `scripts/` (explain, investigate, ai_commit, etc.) using local Ollama LLM
- **Single Source of Truth**: Speech-to-text via `scripts/voice_capture.py:transcribe_file()` (faster-whisper) reused by backend and CLI

## Critical Build & Run Commands

Use `Makefile` (no direct npm/pip calls needed):

```bash
make venv           # Create Python venv
make install        # Install all deps + generate wrapper scripts
make server         # Start FastAPI on http://127.0.0.1:8008/ (with --reload)
make frontend-dev   # Start Vite dev server on http://127.0.0.1:5173/
```

**Workflow**: Always run `make install` first (creates wrappers); then run `make server` and `make frontend-dev` in separate terminals.

## Environment & Configuration

### Key `.env` Variables
- **LLM**: `OLLAMA_URL` (default `http://localhost:11434`), `INVESTIGATE_MODEL`, `AI_COMMIT_MODEL`, `SMART_PARSE_MODEL`
- **Audio**: `WHISPER_MODEL` (default `small`), `WHISPER_DEVICE` (`cpu`/`cuda`), `WHISPER_COMPUTE_TYPE` (`int8`)
- **English Teacher**: `ENGLISH_TEACHER_MODEL`, `ENGLISH_TEACHER_NUM_CTX`, `ENGLISH_TEACHER_TIMEOUT`, `ENGLISH_TEACHER_MODE`

Load via `from scripts.helper.env import load_repo_dotenv` (adds project root to sys.path).

## Patterns & Conventions

### Backend (FastAPI)

- **DB Models** ([server/app/models.py](server/app/models.py)): `Transcript` (STT results), `TeacherReply` (coaching history), `ChatState` (persistent chat per key)
- **Schemas** ([server/app/schemas.py](server/app/schemas.py)): Use Pydantic for request/response validation
- **Audio Conversion**: Use `to_wav_16k_mono()` to convert browser audio (webm/ogg) → WAV 16kHz mono (requires ffmpeg in WSL)
- **Dependency Injection**: Use FastAPI `Depends(get_db)` for `AsyncSession` instead of singletons
- **Single Import Path**: All LLM interactions via `scripts.english_teacher:teach()` and `scripts.voice_capture:transcribe_file()`

### Frontend (React + Tailwind)

- **Hooks Over Components**: Use custom hooks (`useVoiceCapture`, `useTeacherChat`) for state logic; components remain thin
- **Silence Detection**: [useVoiceCapture.ts](frontend/src/components/VoiceCapture/useVoiceCapture.ts) implements client-side voice activity detection (default 850ms silence threshold, 0.014 RMS) before sending to backend
- **Types**: Define in `types.ts` files per component folder (e.g., [VoiceCapture/types.ts](frontend/src/components/VoiceCapture/types.ts)) — import as `import type { Transcript }`
- **Styling**: Tailwind with dark mode support (`dark:` prefix); no CSS-in-JS
- **API Integration**: Direct `fetch()` with JSON responses; handle `{ detail?: string }` error shape from FastAPI

### Python Scripts (CLI Tools)

- **Shared Helpers**: All in `scripts/helper/`:
  - `llm.py`: `ollama_chat(system_prompt, user_prompt, ...)` core interface
  - `env.py`: `load_repo_dotenv()` to set up env + Python path
  - `context.py`: Context limit warnings
  - `spinner.py`: CLI progress spinners
  - `clipboard.py`: Copy results to clipboard
  - `vlm.py`: Vision model utilities (screen capture)
- **Stdin Support**: Tools accept input from stdin, pipes, or files (see [explain.py](scripts/explain.py) pattern)
- **Model Fallback Chain**: `get_default_model()` in [helper/llm.py](scripts/helper/llm.py) prefers `AI_COMMIT_MODEL` → `INVESTIGATE_MODEL` → `llama3.1:8b`

### Text Processing Conventions

- **Transcription Output**: `transcribe_file()` returns `(raw_text, literal_text, meta)` where:
  - `raw_text`: Direct model output
  - `literal_text`: Lowercased, punctuation removed (see `literalize()` in [voice_capture.py](scripts/voice_capture.py))
- **Prompt Construction**: Use `dedent()` from textwrap for multi-line prompts; strip user input with `.strip()` before LLM calls

## Data Flow Examples

### Voice Transcription Flow
1. Frontend: [useVoiceCapture.ts](frontend/src/components/VoiceCapture/useVoiceCapture.ts) records audio → detects silence → POST `/transcribe` (webm blob)
2. Backend: [main.py](server/app/main.py) converts blob to WAV via `to_wav_16k_mono()` → calls `transcribe_file()` from [voice_capture.py](scripts/voice_capture.py)
3. Result: Stored in `Transcript` table; returned as `TranscriptOut` schema with id + raw/literal text

### English Coaching Flow
1. Frontend: `useTeacherChat` batches transcripts → POST `/teach` with user text
2. Backend: Calls `teach()` from [english_teacher.py](scripts/english_teacher.py) → stores reply in `TeacherReply` + updates `ChatState`
3. Response: Returns `TeachOut` with corrections, grammar notes, word alternatives

## Testing & Debugging

- **Local Ollama**: Ensure running on `$OLLAMA_URL` before CLI tool execution
- **FFmpeg**: Required in WSL: `sudo apt install -y ffmpeg` (for audio conversion)
- **TypeScript**: `make frontend-dev` includes `tsc` watch; check console for type errors
- **Python**: Use `from scripts.helper.env import load_repo_dotenv` in scripts to ensure `.env` loading

## File Organization Summary

```
scripts/            # Standalone CLI tools + shared helpers
  ├─ {tool}.py      # entry points (explain, investigate, etc.)
  └─ helper/        # shared utilities (llm, env, spinner, clipboard)
server/app/         # FastAPI backend
  ├─ main.py        # routes, audio conversion
  ├─ models.py      # SQLAlchemy ORM (Transcript, TeacherReply, ChatState)
  ├─ schemas.py     # Pydantic request/response models
  └─ db.py          # engine, async session factory
frontend/src/       # React app
  ├─ App.tsx        # main router (voice, tools, settings pages)
  └─ components/
      └─ VoiceCapture/  # voice recording UI
          ├─ useVoiceCapture.ts  # hooks (silence detection, API calls)
          ├─ types.ts            # TypeScript interfaces
          └─ {Card}.tsx          # UI components
```

## Common Pitfalls

- **Model Reuse**: `voice_capture.py` uses a singleton Whisper model; keep it stateful for performance
- **WSL Audio**: WSL requires special setup; see [main.py](server/app/main.py) comments on `OLLAMA_SKIP_WSL_IP_DETECT`
- **Async DB**: Always use `AsyncSession` with `async with session.begin()` for multi-statement operations
- **Frontend API Errors**: FastAPI returns `{ detail: "..." }`; check both `response.ok` and response body
- **Context Limits**: Monitor context usage with `warn_if_approaching_context()` in helpers before sending to Ollama
