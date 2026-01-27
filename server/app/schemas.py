from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ----------------------------
# Transcripts
# ----------------------------

class PhoneIssue(BaseModel):
    phone: str
    score: float
    alt: str | None = None
    alt_score: float | None = None


class WordScore(BaseModel):
    word: str
    start: float
    end: float
    score: float
    risk: str
    issues: list[PhoneIssue] = Field(default_factory=list)


class PronScoreOut(BaseModel):
    overall_score: float
    overall_risk: str
    words: list[WordScore]


class TranscriptCreateOut(BaseModel):
    id: int
    raw_text: str
    literal_text: str
    pronunciation: PronScoreOut | None = None


class TranscriptOut(BaseModel):
    id: int
    created_at: datetime
    source: str
    raw_text: str
    literal_text: str
    meta: dict[str, Any] = Field(default_factory=dict)


# ----------------------------
# English teacher
# ----------------------------

class Mistake(BaseModel):
    frm: str
    to: str
    why: str


class Pronunciation(BaseModel):
    word: str
    ipa: str
    cue: str


class TeachIn(BaseModel):
    text: str = Field(min_length=1)
    mode: str | None = Field(default=None)
    chat_key: str = Field(min_length=6, max_length=64)
    pronunciation_risks: list[dict[str, Any]] | None = Field(default=None)


class TeachOut(BaseModel):
    corrected_natural: str = ""
    corrected_literal: str = ""
    mistakes: list[Mistake] = Field(default_factory=list)
    pronunciation: list[Pronunciation] = Field(default_factory=list)
    reply: str = ""
    follow_up_question: str = ""
    raw_error: bool = False

class TeacherReplyOut(BaseModel):
    id: int
    created_at: datetime
    chat_key: str
    mode: str
    input_text: str
    output: dict[str, Any]


class TeacherHistoryOut(BaseModel):
    items: list[TeacherReplyOut]


class TeacherModeInfo(BaseModel):
    name: str
    description: str


class ChatSaveIn(BaseModel):
    chat_key: str = Field(min_length=6, max_length=64)
    messages: list[dict[str, Any]] = Field(default_factory=list)


class ChatOut(BaseModel):
    chat_key: str
    updated_at: datetime
    messages: list[dict[str, Any]] = Field(default_factory=list)
