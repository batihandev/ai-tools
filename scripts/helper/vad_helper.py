"""
VAD Helper - Voice Activity Detection using Silero VAD.

Uses Silero VAD for detecting speech end to enable auto-stop recording.
"""
from __future__ import annotations

import io
import wave
from typing import Optional

import numpy as np

# Lazy imports to avoid loading heavy deps unless needed
_vad_model = None
_vad_utils = None


def _load_vad():
    """Lazily load the Silero VAD model and utilities."""
    global _vad_model, _vad_utils
    
    if _vad_model is not None:
        return _vad_model, _vad_utils
    
    try:
        import torch
    except ImportError:
        raise ImportError("torch not installed. Run 'pip install torch'")
    
    # Load Silero VAD model
    _vad_model, _vad_utils = torch.hub.load(
        repo_or_dir='snakers4/silero-vad',
        model='silero_vad',
        force_reload=False,
        onnx=False,
        trust_repo=True,
    )
    
    return _vad_model, _vad_utils


class VADRecorder:
    """
    Voice Activity Detection recorder.
    
    Detects speech end to automatically stop recording after
    a period of silence.
    """
    
    def __init__(
        self,
        silence_threshold: float = 0.5,
        min_speech: float = 0.3,
        max_duration: float = 30.0,
        sample_rate: int = 16000,
    ):
        """
        Initialize the VAD recorder.
        
        Args:
            silence_threshold: Seconds of silence to trigger stop
            min_speech: Minimum seconds of speech before allowing stop
            max_duration: Maximum recording duration in seconds
            sample_rate: Audio sample rate (16000 for VAD model)
        """
        self.silence_threshold = silence_threshold
        self.min_speech = min_speech
        self.max_duration = max_duration
        self.sample_rate = sample_rate
        
        # State tracking
        self._speech_started = False
        self._speech_duration = 0.0
        self._silence_duration = 0.0
        self._total_duration = 0.0
        
    def reset(self) -> None:
        """Reset the VAD state for a new recording session."""
        self._speech_started = False
        self._speech_duration = 0.0
        self._silence_duration = 0.0
        self._total_duration = 0.0
        
        # Reset model state if loaded
        global _vad_model
        if _vad_model is not None:
            _vad_model.reset_states()
    
    def detect_speech_end(self, audio_chunk: bytes, chunk_sample_rate: int = 16000) -> bool:
        """
        Check if speech has ended in the given audio chunk.
        
        Args:
            audio_chunk: Raw PCM audio bytes (16-bit mono)
            chunk_sample_rate: Sample rate of the chunk
            
        Returns:
            True if speech has ended (silence detected after speech)
        """
        model, utils = _load_vad()
        
        import torch
        
        # Convert bytes to numpy array (16-bit PCM to float32)
        audio_np = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32) / 32768.0
        
        # Resample if necessary
        if chunk_sample_rate != self.sample_rate:
            # Simple resampling - for production use librosa or torchaudio
            samples = len(audio_np)
            new_samples = int(samples * self.sample_rate / chunk_sample_rate)
            audio_np = np.interp(
                np.linspace(0, samples, new_samples),
                np.arange(samples),
                audio_np
            )
        
        # Convert to tensor
        audio_tensor = torch.from_numpy(audio_np)
        
        # Calculate chunk duration
        chunk_duration = len(audio_np) / self.sample_rate
        self._total_duration += chunk_duration
        
        # Check max duration
        if self._total_duration >= self.max_duration:
            return True
        
        # Get speech probability
        speech_prob = model(audio_tensor, self.sample_rate).item()
        
        # Update state based on speech probability
        if speech_prob > 0.5:
            self._speech_started = True
            self._speech_duration += chunk_duration
            self._silence_duration = 0.0
        else:
            if self._speech_started:
                self._silence_duration += chunk_duration
        
        # Check if we should stop
        if (
            self._speech_started
            and self._speech_duration >= self.min_speech
            and self._silence_duration >= self.silence_threshold
        ):
            return True
        
        return False
    
    def record_until_silence(self, timeout: Optional[float] = None) -> bytes:
        """
        Record audio until silence is detected after speech.
        
        Args:
            timeout: Optional timeout in seconds (overrides max_duration)
            
        Returns:
            Raw PCM audio bytes (16-bit mono, 16kHz)
            
        Note:
            Requires pyaudio to be installed.
        """
        try:
            import pyaudio
        except ImportError:
            raise ImportError("pyaudio not installed. Run 'pip install pyaudio'")
        
        self.reset()
        
        max_dur = timeout if timeout is not None else self.max_duration
        
        # Audio recording parameters
        chunk_size = int(self.sample_rate * 0.25)  # 250ms chunks
        
        p = pyaudio.PyAudio()
        
        try:
            stream = p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=chunk_size,
            )
            
            audio_buffer = bytearray()
            
            while self._total_duration < max_dur:
                chunk = stream.read(chunk_size, exception_on_overflow=False)
                audio_buffer.extend(chunk)
                
                if self.detect_speech_end(chunk, self.sample_rate):
                    break
                    
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()
        
        return bytes(audio_buffer)
    
    def save_to_wav(self, audio_bytes: bytes, output_path: str) -> str:
        """
        Save raw PCM audio bytes to a WAV file.
        
        Args:
            audio_bytes: Raw PCM audio bytes (16-bit mono)
            output_path: Path to save the WAV file
            
        Returns:
            Path to the saved WAV file
        """
        with wave.open(output_path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_bytes)
        
        return output_path


# Convenience function for simple use cases
def record_with_vad(
    silence_threshold: float = 0.5,
    min_speech: float = 0.3,
    max_duration: float = 30.0,
) -> bytes:
    """
    Record audio with VAD until silence is detected.
    
    Args:
        silence_threshold: Seconds of silence to trigger stop
        min_speech: Minimum seconds of speech before allowing stop
        max_duration: Maximum recording duration in seconds
        
    Returns:
        Raw PCM audio bytes (16-bit mono, 16kHz)
    """
    recorder = VADRecorder(
        silence_threshold=silence_threshold,
        min_speech=min_speech,
        max_duration=max_duration,
    )
    return recorder.record_until_silence()
