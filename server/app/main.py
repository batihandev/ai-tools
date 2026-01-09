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
)
from sqlalchemy import select
from pydantic import BaseModel
from scripts.english_teacher import teach

# Single source of truth for STT
from scripts.voice_capture import transcribe_file

load_dotenv()


def to_wav_16k_mono(src_path: str, dst_path: str) -> None:
    """
    Convert browser-recorded audio (webm/ogg/etc.) to 16kHz mono WAV.
    Requires ffmpeg installed in WSL: sudo apt install -y ffmpeg
    """
    p = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i", src_path,
            "-ac", "1",
            "-ar", "16000",
            "-vn",
            dst_path,
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if p.returncode != 0:
        err = (p.stderr or "").strip()
        raise subprocess.CalledProcessError(p.returncode, p.args, output=None, stderr=err)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown: nothing for now


app = FastAPI(title="ai-scripts local server", lifespan=lifespan)



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
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix or ".webm") as tmp:
            src_tmp_path = tmp.name
            tmp.write(await audio.read())

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as wtmp:
            wav_tmp_path = wtmp.name

        to_wav_16k_mono(src_tmp_path, wav_tmp_path)

        raw_text, literal_text, meta = transcribe_file(wav_tmp_path)

    except subprocess.CalledProcessError as e:
        detail = (getattr(e, "stderr", "") or "").strip() or str(e)
        raise HTTPException(status_code=500, detail=f"Audio decode failed (ffmpeg): {detail}")

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
        out = teach(text=text, mode=mode)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"english-teacher failed: {type(e).__name__}: {e}")

    # Persist teacher reply
    row = TeacherReply(
        chat_key=chat_key,
        mode=mode,
        input_text=text,
        output=dict(out),
    )
    db.add(row)
    await db.commit()

    return TeachOut(**out)

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
