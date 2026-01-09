from __future__ import annotations
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source: Mapped[str] = mapped_column(Text, default="browser")

    raw_text: Mapped[str] = mapped_column(Text)
    literal_text: Mapped[str] = mapped_column(Text)

    meta: Mapped[dict] = mapped_column(JSONB, default=dict)

class TeacherReply(Base):
    __tablename__ = "teacher_replies"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # lets you group replies by chat/session
    chat_key: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="coach")

    # what we sent to teacher (combined batch)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)

    # full teacher JSON response (TeachOut shape)
    output: Mapped[dict] = mapped_column(JSONB, nullable=False)


class ChatState(Base):
    """
    Stores the current chat transcript for a key.
    Client keeps updating this row while chatting.
    """
    __tablename__ = "chat_states"

    # key is provided by frontend (stable until "Clear")
    chat_key: Mapped[str] = mapped_column(String(64), primary_key=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # store chat messages as JSON array [{id, role, text, ts}, ...]
    messages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
