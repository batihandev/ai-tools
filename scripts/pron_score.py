#!/usr/bin/env python3
"""
pron_score — Pronunciation scoring layer (MVP).

Analyzes audio segments (from Whisper) to calculate word-level "risk" scores.
Phase 1: Uses Whisper confidence (probability) as the primary proxy for pronunciation quality.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from typing import List, Dict, Any, Optional

from pydantic import BaseModel, Field

# Import phoneme analysis (optional, graceful degradation)
try:
    from .phoneme_analysis import (
        get_expected_phonemes,
        format_phonemes,
        analyze_prosody,
        ProsodyMetrics,
    )
    HAS_PHONEME_ANALYSIS = True
except ImportError:
    HAS_PHONEME_ANALYSIS = False
    ProsodyMetrics = None

# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------

class PhoneIssue(BaseModel):
    phone: str
    score: float
    alt: Optional[str] = None
    alt_score: Optional[float] = None

class WordScore(BaseModel):
    word: str
    start: float
    end: float
    score: float
    risk: str  # low|medium|high
    issues: List[PhoneIssue] = Field(default_factory=list)
    expected_phonemes: List[str] = Field(default_factory=list)
    fluency_score: float = 1.0

class ProsodyOut(BaseModel):
    pitch_mean: float = 0.0
    pitch_std: float = 0.0
    intensity_mean: float = 0.0
    speaking_rate: float = 0.0

class PronScoreOut(BaseModel):
    overall_score: float
    overall_risk: str
    overall_fluency: float = 1.0
    prosody: Optional[ProsodyOut] = None
    words: List[WordScore]

# -----------------------------------------------------------------------------
# Scoring Logic
# -----------------------------------------------------------------------------

def measure_pronunciation(
    segments: List[Dict[str, Any]],
    transcript: str = ""
) -> PronScoreOut:
    """
    Compute pronunciation scores from Whisper segments.
    
    Args:
        segments: List of dicts with 'start', 'end', 'text', and optional 'words'.
        transcript: Full text (unused in this MVP, but good for alignment).
    
    Returns:
        PronScoreOut object.
    """
    word_scores: List[WordScore] = []
    
    # Flatten all words from all segments
    all_words: List[Dict[str, Any]] = []
    for seg in segments:
        if seg.get("words"):
            all_words.extend(seg["words"])
        else:
            # Fallback if no word timestamps: treat segment as one "word" (not ideal but safe)
            # Or better, split by space and distribute time linearly? 
            # For MVP with word_timestamps=True, we expect 'words' to be present.
            pass

    if not all_words:
        # If no word level info, return empty or safe default
        return PronScoreOut(overall_score=1.0, overall_risk="low", words=[])

    scores = []
    
    for w in all_words:
        word_text = w.get("word", "").strip()
        start = w.get("start", 0.0)
        end = w.get("end", 0.0)
        prob = w.get("probability", 1.0)
        duration = end - start
        
        # Duration-based adjustments
        # Very short words (< 0.1s) may be rushed/mumbled
        # Very long words (> 1.5s) may indicate hesitation
        duration_factor = 1.0
        if duration < 0.1 and len(word_text) > 2:
            duration_factor = 0.85  # Penalize rushed speech
        elif duration > 1.5:
            duration_factor = 0.90  # Slight penalty for hesitation
        
        # Combined score: probability adjusted by duration factor
        adjusted_score = prob * duration_factor
        
        # Risk thresholds
        risk = "low"
        if adjusted_score < 0.4:
            risk = "high"
        elif adjusted_score < 0.75:
            risk = "medium"
            
        scores.append(adjusted_score)
        
        # Get expected phonemes if available
        expected_phonemes: List[str] = []
        fluency_score = 1.0
        if HAS_PHONEME_ANALYSIS:
            expected_phonemes = get_expected_phonemes(word_text)
            # Fluency based on duration vs expected (0.08s per phoneme)
            expected_duration = len(expected_phonemes) * 0.08 if expected_phonemes else 0.3
            if expected_duration > 0:
                duration_ratio = duration / expected_duration
                if duration_ratio < 0.5:
                    fluency_score = 0.5
                elif duration_ratio > 2.0:
                    fluency_score = 0.6
                else:
                    fluency_score = 1.0 - abs(1.0 - duration_ratio) * 0.3
                fluency_score = max(0.0, min(1.0, fluency_score))
        
        word_scores.append(WordScore(
            word=word_text,
            start=start,
            end=end,
            score=adjusted_score,
            risk=risk,
            issues=[],
            expected_phonemes=expected_phonemes,
            fluency_score=fluency_score,
        ))

    overall_avg = statistics.mean(scores) if scores else 0.0
    overall_risk = "low"
    if overall_avg < 0.6:
        overall_risk = "high"
    elif overall_avg < 0.8:
        overall_risk = "medium"

    # Calculate overall fluency
    fluency_scores = [ws.fluency_score for ws in word_scores]
    overall_fluency = statistics.mean(fluency_scores) if fluency_scores else 1.0

    return PronScoreOut(
        overall_score=overall_avg,
        overall_risk=overall_risk,
        overall_fluency=overall_fluency,
        prosody=None,  # TODO: Add prosody analysis when audio_path is available
        words=word_scores
    )

# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Calculate pronunciation scores from transcription data.")
    parser.add_argument("--json", required=True, help="Input JSON file (output from voice-capture)")
    args = parser.parse_args()

    try:
        with open(args.json, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        segments = data.get("segments", [])
        if not segments and "raw_text" in data:
            # Maybe the user didn't have segments?
            # We can't do much without segments.
            print(json.dumps({"error": "No segments found in input JSON"}, indent=2))
            sys.exit(1)

        result = measure_pronunciation(segments)
        print(result.model_dump_json(indent=2))
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
