from __future__ import annotations

import os
import subprocess
import tempfile
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import engine, get_db
from .models import Base, Transcript, TeacherReply, ChatState
from .schemas import (
    TeachIn, TeachOut,
    ChatSaveIn, ChatOut,
    TeacherReplyOut,
    TranscriptCreateOut, TranscriptOut,
    TeacherModeInfo,
)
from sqlalchemy import select
from pydantic import BaseModel
from scripts.english_teacher import teach
from scripts.helper.ollama_utils import resolve_ollama_url
import httpx

# Single source of truth for STT
from scripts.voice_capture import transcribe_file, convert_to_wav
from scripts.pron_score import measure_pronunciation
from scripts.tts import generate_word_pronunciation

load_dotenv()

OLLAMA_URL = resolve_ollama_url("http://localhost:11434")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown: nothing for now


app = FastAPI(title="ai-scripts local server", lifespan=lifespan)


class HealthOut(BaseModel):
    ollama_status: str
    ollama_url: str


@app.get("/api/health", response_model=HealthOut)
async def health_check():
    """Check if Ollama is accessible"""
    status = "offline"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            try:
                resp = await client.get(f"{OLLAMA_URL}/api/tags", follow_redirects=True)
                if resp.status_code == 200:
                    status = "online"
                    print(f"[Health] ✓ Ollama online at {OLLAMA_URL}")
                else:
                    print(f"[Health] Ollama responded with {resp.status_code} at {OLLAMA_URL}")
                    status = "error"
            except httpx.ConnectError as e:
                print(f"[Health] Connection error to {OLLAMA_URL}: {e}")
                status = "offline"
            except httpx.TimeoutException as e:
                print(f"[Health] Timeout connecting to {OLLAMA_URL}: {e}")
                status = "offline"
            except Exception as e:
                print(f"[Health] Error checking Ollama at {OLLAMA_URL}: {type(e).__name__}: {e}")
                status = "error"
    except Exception as e:
        print(f"[Health] Unexpected error: {type(e).__name__}: {e}")
        status = "offline"
    
    return HealthOut(ollama_status=status, ollama_url=OLLAMA_URL)


@app.get("/api/english/modes", response_model=list[TeacherModeInfo])
async def get_teacher_modes():
    """Get available English teacher modes with descriptions"""
    return [
        TeacherModeInfo(
            name="coach",
            description="Continue the conversation naturally. Keep it friendly, practical, and engage with follow-up questions."
        ),
        TeacherModeInfo(
            name="strict",
            description="Be thorough and include all mistakes. Provide IPA pronunciation for any word that might be mispronounced."
        ),
        TeacherModeInfo(
            name="correct",
            description="Show corrections only—no conversation or follow-up questions. Best for quick grammar fixes."
        ),
    ]


class TTSRequest(BaseModel):
    word: str
    accent: str = "us"  # us, uk, au


@app.post("/api/tts/pronounce")
async def pronounce_word(req: TTSRequest):
    """Generate pronunciation audio for a word using Edge TTS."""
    from fastapi.responses import Response
    
    if not req.word.strip():
        raise HTTPException(status_code=400, detail="Missing word")
    
    try:
        audio_bytes = generate_word_pronunciation(req.word.strip(), req.accent)
        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={"Content-Disposition": f"inline; filename={req.word}.mp3"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS failed: {e}")


@app.post("/api/voice/transcribe", response_model=TranscriptCreateOut)
async def transcribe_voice(
    audio: Annotated[UploadFile, File(...)],
    db: AsyncSession = Depends(get_db),
):
    if not audio.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    suffix = Path(audio.filename).suffix.lower()
    src_tmp_path: str | None = None
    wav_tmp_path: str | None = None

    try:
        audio_bytes = await audio.read()
        
        # Validate audio size (minimum 4KB, maximum 100MB)
        if len(audio_bytes) < 4096:
            raise HTTPException(status_code=400, detail="Audio file too small (likely empty or corrupted)")
        if len(audio_bytes) > 100 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Audio file too large (max 100MB)")
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix or ".webm") as tmp:
            src_tmp_path = tmp.name
            tmp.write(audio_bytes)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as wtmp:
            wav_tmp_path = wtmp.name

        # Use shared utility from voice_capture
        convert_to_wav(src_tmp_path, wav_tmp_path)

        raw_text, literal_text, segments, meta = transcribe_file(wav_tmp_path)

        # Calculate pronunciation score
        pron = measure_pronunciation(segments, raw_text)
        meta["pronunciation"] = pron.model_dump()

        # Skip storing empty transcriptions
        if not (raw_text or literal_text) or (
            not raw_text.strip() and not literal_text.strip()
        ):
            raise HTTPException(
                status_code=400,
                detail="Empty transcription (no speech detected)",
            )

    except RuntimeError as e:
        # Voice capture utility raises RuntimeError for ffmpeg failures
        detail = str(e)
        raise HTTPException(status_code=500, detail=f"Audio decode failed: {detail}")

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Transcription failed: {type(e).__name__}: {e}")

    finally:
        for p in (src_tmp_path, wav_tmp_path):
            if p:
                try:
                    os.unlink(p)
                except Exception:
                    pass

    row = Transcript(
        source="browser",
        raw_text=raw_text,
        literal_text=literal_text,
        meta=meta,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    return TranscriptCreateOut(
        id=row.id,
        raw_text=row.raw_text,
        literal_text=row.literal_text,
        pronunciation=meta.get("pronunciation"),
    )


@app.get("/api/transcripts", response_model=list[TranscriptOut])
async def list_transcripts(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    limit = max(1, min(limit, 200))
    q = select(Transcript).order_by(Transcript.id.desc()).limit(limit)
    res = await db.execute(q)
    rows = res.scalars().all()

    return [
        TranscriptOut(
            id=r.id,
            created_at=r.created_at,
            source=r.source,
            raw_text=r.raw_text,
            literal_text=r.literal_text,
            meta=r.meta or {},
        )
        for r in rows
    ]


@app.post("/api/english/teach", response_model=TeachOut)
async def english_teach(payload: TeachIn, db: AsyncSession = Depends(get_db)):
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Missing 'text'")

    mode = (payload.mode or "coach").strip().lower()
    if mode not in {"coach", "strict", "correct"}:
        raise HTTPException(status_code=400, detail="mode must be one of: coach, strict, correct")

    # You said: save chat under a key. So require it here too.
    # If you prefer optional, make it optional in TeachIn and default to "default".
    chat_key = getattr(payload, "chat_key", None)
    if not chat_key:
        raise HTTPException(status_code=400, detail="Missing 'chat_key'")

    try:
        out = teach(
            text=text,
            mode=mode,
            pronunciation_risks=payload.pronunciation_risks,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"english-teacher failed: {type(e).__name__}: {e}")

    # `teach()` returns a Pydantic model from `scripts.english_teacher`.
    # Convert it to a plain mapping for DB persistence + FastAPI response schema.
    if hasattr(out, "model_dump"):
        out_data = out.model_dump()  # pydantic v2
    elif hasattr(out, "dict"):
        out_data = out.dict()  # pydantic v1
    else:
        out_data = out

    # Persist teacher reply
    row = TeacherReply(
        chat_key=chat_key,
        mode=mode,
        input_text=text,
        output=out_data,
    )
    db.add(row)
    await db.commit()

    return TeachOut(**out_data)


@app.get("/api/english/history", response_model=list[TeacherReplyOut])
async def english_history(limit: int = 50, db: AsyncSession = Depends(get_db)):
    limit = max(1, min(limit, 200))
    q = select(TeacherReply).order_by(TeacherReply.id.desc()).limit(limit)
    res = await db.execute(q)
    rows = res.scalars().all()
    return [
        TeacherReplyOut(
            id=r.id,
            created_at=r.created_at,
            chat_key=r.chat_key,
            mode=r.mode,
            input_text=r.input_text,
            output=r.output,
        )
        for r in rows
    ]


@app.post("/api/chat/save", response_model=ChatOut)
async def chat_save(payload: ChatSaveIn, db: AsyncSession = Depends(get_db)):
    key = payload.chat_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="Missing chat_key")

    q = select(ChatState).where(ChatState.chat_key == key)
    res = await db.execute(q)
    row = res.scalar_one_or_none()

    if row is None:
        row = ChatState(chat_key=key, messages=payload.messages)
        db.add(row)
    else:
        row.messages = payload.messages

    await db.commit()
    await db.refresh(row)

    return ChatOut(chat_key=row.chat_key, updated_at=row.updated_at, messages=row.messages or [])


@app.get("/api/chat/get", response_model=ChatOut)
async def chat_get(chat_key: str, db: AsyncSession = Depends(get_db)):
    key = (chat_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="Missing chat_key")

    q = select(ChatState).where(ChatState.chat_key == key)
    res = await db.execute(q)
    row = res.scalar_one_or_none()
    if row is None:
        # return empty chat (client can treat as new)
        raise HTTPException(status_code=404, detail="Chat not found")

    return ChatOut(chat_key=row.chat_key, updated_at=row.updated_at, messages=row.messages or [])
