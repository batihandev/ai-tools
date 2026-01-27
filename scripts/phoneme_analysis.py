#!/usr/bin/env python3
"""
phoneme_analysis — Phoneme-level pronunciation analysis.

Uses:
- g2p-en: Grapheme-to-phoneme conversion (text → expected phonemes)
- Parselmouth: Prosody extraction (pitch, intensity, formants)
- Word timestamps from Whisper: Timing alignment

This module provides phoneme-level scoring without requiring MFA installation,
using a simpler approach based on expected phonemes + prosody analysis.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

try:
    import parselmouth
    from parselmouth.praat import call
    HAS_PARSELMOUTH = True
except ImportError:
    HAS_PARSELMOUTH = False

try:
    from g2p_en import G2p
    HAS_G2P = True
    _g2p = None
except ImportError:
    HAS_G2P = False
    _g2p = None


def _get_g2p():
    """Lazy-load G2P model."""
    global _g2p
    if _g2p is None and HAS_G2P:
        _g2p = G2p()
    return _g2p


@dataclass
class PhonemeScore:
    phoneme: str
    expected: bool  # Was this phoneme expected?
    score: float    # 0-1 confidence


@dataclass
class ProsodyMetrics:
    """Prosody analysis results."""
    pitch_mean: float = 0.0
    pitch_std: float = 0.0
    intensity_mean: float = 0.0
    speaking_rate: float = 0.0  # syllables per second estimate
    pause_ratio: float = 0.0    # ratio of silence to speech


@dataclass
class WordPhonemeAnalysis:
    word: str
    expected_phonemes: List[str]
    duration: float
    pitch_mean: float
    intensity_mean: float
    fluency_score: float  # Based on duration vs expected


@dataclass
class PhonemeAnalysisResult:
    """Complete phoneme analysis for an utterance."""
    words: List[WordPhonemeAnalysis] = field(default_factory=list)
    prosody: ProsodyMetrics = field(default_factory=ProsodyMetrics)
    overall_fluency: float = 0.0
    overall_pronunciation: float = 0.0


def get_expected_phonemes(word: str) -> List[str]:
    """Get expected phonemes for a word using G2P."""
    g2p = _get_g2p()
    if g2p is None:
        return []
    
    try:
        phonemes = g2p(word)
        # Filter out non-phoneme tokens (spaces, etc.)
        return [p for p in phonemes if p.strip() and p not in [' ', '']]
    except Exception:
        return []


def analyze_prosody(audio_path: str) -> ProsodyMetrics:
    """Extract prosody metrics from audio using Parselmouth."""
    if not HAS_PARSELMOUTH:
        return ProsodyMetrics()
    
    try:
        sound = parselmouth.Sound(audio_path)
        
        # Pitch analysis
        pitch = call(sound, "To Pitch", 0.0, 75, 600)
        pitch_values = pitch.selected_array['frequency']
        pitch_values = [p for p in pitch_values if p > 0]  # Filter unvoiced
        
        pitch_mean = statistics.mean(pitch_values) if pitch_values else 0.0
        pitch_std = statistics.stdev(pitch_values) if len(pitch_values) > 1 else 0.0
        
        # Intensity analysis
        intensity = call(sound, "To Intensity", 75, 0.0)
        intensity_values = [call(intensity, "Get value at time", t, "cubic") 
                          for t in [i * 0.01 for i in range(int(sound.duration * 100))]]
        intensity_values = [v for v in intensity_values if v and v > 0]
        intensity_mean = statistics.mean(intensity_values) if intensity_values else 0.0
        
        # Speaking rate estimate (based on intensity peaks)
        duration = sound.duration
        # Rough estimate: count syllables by intensity peaks
        speaking_rate = len(pitch_values) / duration if duration > 0 else 0.0
        
        return ProsodyMetrics(
            pitch_mean=pitch_mean,
            pitch_std=pitch_std,
            intensity_mean=intensity_mean,
            speaking_rate=speaking_rate,
            pause_ratio=0.0,  # Would need VAD for accurate pause detection
        )
    except Exception as e:
        print(f"Prosody analysis error: {e}")
        return ProsodyMetrics()


def analyze_word_phonemes(
    word: str,
    start: float,
    end: float,
    audio_path: str,
) -> WordPhonemeAnalysis:
    """Analyze a single word for phoneme and prosody features."""
    duration = end - start
    expected = get_expected_phonemes(word)
    
    # Expected duration heuristic: ~0.08s per phoneme for native speech
    expected_duration = len(expected) * 0.08 if expected else 0.3
    
    # Fluency score: how close is actual duration to expected?
    if expected_duration > 0:
        duration_ratio = duration / expected_duration
        # Ideal ratio is 1.0, penalize deviation
        if duration_ratio < 0.5:
            fluency = 0.5  # Too fast
        elif duration_ratio > 2.0:
            fluency = 0.6  # Too slow
        else:
            fluency = 1.0 - abs(1.0 - duration_ratio) * 0.3
    else:
        fluency = 0.8
    
    return WordPhonemeAnalysis(
        word=word,
        expected_phonemes=expected,
        duration=duration,
        pitch_mean=0.0,  # Would need segment extraction for per-word pitch
        intensity_mean=0.0,
        fluency_score=max(0.0, min(1.0, fluency)),
    )


def analyze_pronunciation(
    audio_path: str,
    words: List[Dict[str, Any]],
    transcript: str = "",
) -> PhonemeAnalysisResult:
    """
    Full pronunciation analysis combining phoneme expectations and prosody.
    
    Args:
        audio_path: Path to audio file
        words: List of word dicts from Whisper (word, start, end, probability)
        transcript: Full transcript text
    
    Returns:
        PhonemeAnalysisResult with detailed analysis
    """
    result = PhonemeAnalysisResult()
    
    # Analyze prosody for full utterance
    result.prosody = analyze_prosody(audio_path)
    
    # Analyze each word
    fluency_scores = []
    for w in words:
        word_text = w.get("word", "").strip()
        if not word_text:
            continue
            
        analysis = analyze_word_phonemes(
            word=word_text,
            start=w.get("start", 0.0),
            end=w.get("end", 0.0),
            audio_path=audio_path,
        )
        result.words.append(analysis)
        fluency_scores.append(analysis.fluency_score)
    
    # Overall scores
    if fluency_scores:
        result.overall_fluency = statistics.mean(fluency_scores)
        # Combine with Whisper confidence if available
        probs = [w.get("probability", 0.8) for w in words if w.get("probability")]
        result.overall_pronunciation = statistics.mean(probs) if probs else 0.8
    
    return result


def format_phonemes(phonemes: List[str]) -> str:
    """Format phoneme list as IPA-like string."""
    return "/" + " ".join(phonemes) + "/" if phonemes else ""
