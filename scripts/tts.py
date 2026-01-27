#!/usr/bin/env python3
"""
tts — Text-to-Speech using Edge TTS (free Microsoft voices).
"""
from __future__ import annotations

import asyncio
import io
from typing import Optional

try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False


# Default voice: US English, natural female
DEFAULT_VOICE = "en-US-AriaNeural"

# Available voices for different accents
VOICES = {
    "us": "en-US-AriaNeural",
    "uk": "en-GB-SoniaNeural", 
    "au": "en-AU-NatashaNeural",
}


async def _generate_speech_async(text: str, voice: str = DEFAULT_VOICE) -> bytes:
    """Generate speech audio bytes from text."""
    if not HAS_EDGE_TTS:
        raise RuntimeError("edge-tts not installed. Run: pip install edge-tts")
    
    communicate = edge_tts.Communicate(text, voice)
    audio_bytes = b""
    
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_bytes += chunk["data"]
    
    return audio_bytes


def generate_speech(text: str, voice: str = DEFAULT_VOICE) -> bytes:
    """Synchronous wrapper for speech generation."""
    return asyncio.run(_generate_speech_async(text, voice))


def generate_word_pronunciation(word: str, accent: str = "us") -> bytes:
    """Generate pronunciation audio for a single word.
    
    Args:
        word: The word to pronounce
        accent: 'us', 'uk', or 'au'
    
    Returns:
        MP3 audio bytes
    """
    voice = VOICES.get(accent, DEFAULT_VOICE)
    # Speak the word slowly and clearly
    return generate_speech(word, voice)
