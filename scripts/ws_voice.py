"""
WebSocket Voice Handler - Real-time voice streaming for English Teacher.

Provides WebSocket endpoint for real-time voice conversation with
VAD-based auto-stop and low-latency response streaming.
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
import sys
from functools import partial
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import WebSocket, WebSocketDisconnect

from scripts.helper.vad_helper import VADRecorder
from scripts.english_teacher import teach, TeachCfg
from scripts.helper.colors import Colors

# Configure logger
logger = logging.getLogger(__name__)

async def voice_stream_handler(
    ws: WebSocket,
    session_id: str,
    mode: str = "coach",
) -> None:
    """
    WebSocket handler for real-time voice conversation.
    
    Protocol:
    - Client sends audio chunks (raw PCM, 16-bit mono, 16kHz)
    - Server detects speech end via VAD
    - Server processes audio in a background thread to avoid blocking the event loop
    - Server returns:
      - JSON message: {"type": "text", "data": {...}}
      - Binary audio response
    
    Args:
        ws: WebSocket connection
        session_id: Conversation session identifier
        mode: Teaching mode (coach/strict/correct)
    """
    await ws.accept()
    
    vad = VADRecorder(
        silence_threshold=0.5,
        min_speech=0.3,
        max_duration=30.0,
    )
    audio_buffer = bytearray()
    loop = asyncio.get_running_loop()
    
    try:
        while True:
            # Receive audio chunks from client
            try:
                chunk = await asyncio.wait_for(
                    ws.receive_bytes(),
                    timeout=60.0,  # 1 minute timeout for inactivity
                )
            except asyncio.TimeoutError:
                await ws.send_json({
                    "type": "timeout",
                    "message": "No audio received for 60 seconds",
                })
                break
            
            audio_buffer.extend(chunk)
            
            # Check for speech end
            if vad.detect_speech_end(chunk):
                # Process accumulated audio in a separate thread
                # This prevents blocking the asyncio loop during heavy model inference
                try:
                    # Capture current buffer and copy it to bytes for thread safety
                    current_audio = bytes(audio_buffer)
                    
                    # Run blocking inference in executor
                    result = await loop.run_in_executor(
                        None,  # Use default executor (ThreadPoolExecutor)
                        partial(_process_voice_sync, current_audio, session_id, mode)
                    )
                    
                    # Send text response
                    await ws.send_json({
                        "type": "text",
                        "data": result["text_response"],
                    })
                    
                    # Send audio response if available
                    if result.get("audio_bytes"):
                        await ws.send_bytes(result["audio_bytes"])
                        
                except Exception as e:
                    logger.error(f"Error processing voice: {e}", exc_info=True)
                    await ws.send_json({
                        "type": "error",
                        "message": f"Processing error: {str(e)}",
                    })
                
                # Reset for next utterance
                audio_buffer.clear()
                vad.reset()
                
    except WebSocketDisconnect:
        pass  # Normal disconnect
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        try:
            await ws.send_json({
                "type": "error",
                "message": str(e),
            })
        except Exception:
            pass 


def _process_voice_sync(
    audio: bytes,
    session_id: str,
    mode: str = "coach",
) -> Dict[str, Any]:
    """
    Synchronous worker function to process voice input.
    
    Args:
        audio: Raw PCM audio bytes (16-bit mono, 16kHz)
        session_id: Session identifier for context
        mode: Teaching mode
        
    Returns:
        Dict with 'text_response' (TeachOut dict) and optional 'audio_bytes'
    """
    import soundfile as sf
    import numpy as np
    
    # Save audio to temp file (Omni needs file path)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
        
        # Convert raw PCM to WAV
        # Note: numpy usage here is fast enough, but heavy lifting is done by Omni
        audio_np = np.frombuffer(audio, dtype=np.int16)
        sf.write(tmp_path, audio_np, 16000)
    
    try:
        # Transcribe audio using Omni
        from scripts.helper.omni_helper import OmniHelper
        transcription = OmniHelper.transcribe(tmp_path)
        
        if not transcription or not transcription.strip():
            # Handle empty transcription gracefully
            return {
                "text_response": {
                    "corrected_natural": "",
                    "corrected_literal": "",
                    "mistakes": [],
                    "pronunciation": [],
                    "reply": "I couldn't hear that clearly.",
                    "follow_up_question": "",
                    "raw_output": "",
                },
                "audio_bytes": None,
            }

        # Get teaching response (session_id passed for history tracking)
        cfg = TeachCfg(mode=mode)
        response = teach(
            text=transcription,
            mode=mode,
            cfg=cfg,
            session_id=session_id,
        )
        
        # Prepare result
        result = {
            "text_response": {
                "transcription": transcription,
                "corrected_natural": response.corrected_natural,
                "corrected_literal": response.corrected_literal,
                "mistakes": [m.model_dump() for m in response.mistakes],
                "pronunciation": [p.model_dump() for p in response.pronunciation],
                "reply": response.reply,
                "follow_up_question": response.follow_up_question,
            },
            "audio_bytes": None,
        }
        
        # Read audio response if generated
        if response.audio_path:
            # Convert relative path to absolute
            repo_root = Path(__file__).resolve().parents[1]
            # audio_path from teach() is relative like "/audios/uuid.wav"
            # It expects to be in frontend/public
            audio_file = repo_root / "frontend" / "public" / response.audio_path.lstrip("/")
            
            if audio_file.exists():
                with open(audio_file, "rb") as f:
                    result["audio_bytes"] = f.read()
        
        return result
        
    finally:
        # Cleanup temp file
        Path(tmp_path).unlink(missing_ok=True)
