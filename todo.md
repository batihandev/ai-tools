Below is a concrete, buildable plan that fits your current setup (Whisper transcription → LLM coach) and adds a **middle scoring layer**: **audio + transcript → word/phoneme alignment → per-word “pronunciation risk” + per-phone hints**.

The goal is not “perfect mispronunciation detection” (free speech makes that impossible), but **reliable highlighting**: _“these words/phones acoustically don’t match canonical pronunciation of the recognized word.”_

---

## Target architecture

### Current

`audio -> voice-capture (whisper) -> transcript -> english-teacher (LLM) -> feedback`

### Add

`audio + transcript -> pronunciation-score (alignment + GOP-like scoring) -> json report`
Then feed the report into your LLM prompt (or show directly in UI).

So:
`audio -> whisper transcript`
`audio + transcript -> score -> (highlight suspect words + cues)`
`transcript + score -> LLM`

---

## Layer spec (what you will implement)

### New module

`scripts/pron_score.py` (importable + CLI)

**Input**

- `audio_path` (wav 16k mono; you already normalize via ffmpeg)
- `transcript` (raw or literal)
- optional `whisper_segments` timestamps if you want to keep segment boundaries later

**Output JSON**

```json
{
  "audio": "...",
  "model": { "aligner": "...", "acoustic": "..." },
  "overall": { "score": 0.78, "risk": "medium" },
  "words": [
    {
      "word": "think",
      "start": 1.23,
      "end": 1.54,
      "score": 0.42,
      "risk": "high",
      "top_phone_issues": [
        { "phone": "TH", "score": 0.28, "alt": "T", "alt_score": 0.61 }
      ]
    }
  ],
  "debug": { "notes": [] }
}
```

This JSON is the “middle layer contract” between STT and your LLM.

---

## Implementation plan (phased, concrete)

### Phase 1 — Word-level alignment + word “risk score” (fast MVP, minimal moving parts)

**Goal:** highlight suspicious words without phonemes yet.

1. **Keep Whisper segments with timestamps**
   - Change `transcribe_file()` to also return segment list:
     - `[{start, end, text}]`

   - That’s enough to locate audio windows per segment.

2. **Align transcript to time more precisely**
   - Use `whisperx` alignment (it uses wav2vec2 alignment models).
   - Output word timestamps: `[{word, start, end, score?}]`
   - If you don’t want WhisperX dependency yet, you can start with Whisper segment timestamps (coarser), but WhisperX makes it usable.

3. **Word “risk” scoring**
   - MVP heuristic: low alignment confidence + weird duration -> high risk
   - Score features:
     - `duration = end-start`
     - `duration_z` relative to typical English word duration (or relative to speaker median)
     - `align_conf` from whisperx if available

   - Combine to `word_score ∈ [0,1]`, where lower = worse.

**Deliverable**

- `pron_score.py` outputs `words[]` with `start/end/risk/score`.

**Why this is worth doing**

- You can ship UI highlighting + “replay this word” immediately.
- It sets up the data model for Phase 2.

---

### Phase 2 — Phone-level alignment + GOP-like scoring (actual pronunciation layer)

**Goal:** identify which part of the word is off (TH vs T, R coloring, vowel issues).

You’ll add:

- G2P (word → phones)
- phone alignment (phones → time)
- acoustic posterior scoring (audio frames → phones)
- compute per-phone “goodness” + confusion alternatives

#### 2A) G2P (English)

Use one of these:

- **g2p-en** (simple, common)
- **phonemizer** with espeak-ng (also fine; slightly different phone sets)

Store phones in ARPAbet-like tokens (easy).

#### 2B) Phone alignment

Best practical choice: **Montreal Forced Aligner (MFA)** in a subprocess.

Flow:

- Create a temporary “transcript file” and run MFA on the audio.
- MFA outputs TextGrid with word+phone boundaries.
- Parse TextGrid → `words[]` + `phones[]` with timestamps.

Notes:

- MFA needs a lexicon. Use its built-in English dictionary + G2P fallback.

#### 2C) Phone posterior scoring (the actual “GOP”)

Use a **CTC acoustic model** that gives frame-level posteriors.
Two practical approaches:

**Approach 1 (simpler): use MFA acoustic likelihood proxy**

- MFA internally uses an acoustic model; you can extract alignment confidence indirectly, but it’s not great.

**Approach 2 (recommended): wav2vec2-CTC phoneme model**

- Use a pretrained wav2vec2 (or hubert) fine-tuned for phoneme/ASR CTC.
- Compute per-frame logits, convert to posteriors.
- For each aligned phone segment:
  - `p(phone)` average over frames
  - compute margin vs best alternate phone
  - entropy as uncertainty

Output:

- per-phone score
- top alternative phone if it consistently beats the aligned phone

This gives you the “TH→T” style flags.

#### 2D) Convert phones back to actionable cues

Map phone issues to learner-facing hints:

- `TH weak, T strong` -> “tongue between teeth”
- `IH vs IY` -> “short i vs long ee”
- `R` weak -> “tongue up/back, not rolled”

Keep this as a small curated mapping table (do not ask LLM to invent physiology).

---

### Phase 3 — Integrate with your `english-teacher` prompt

Add a new optional field in your LLM input:

- Current: transcript only.
- New: transcript + `pron_score` report.

Change system prompt guidance:

- “Only include pronunciation tips for words flagged `risk=high` OR frequently mispronounced words”
- Provide IPA + cue (you already do)
- Optionally include “I heard: TH sounded closer to T” when your scoring says so.

This reduces LLM hallucinations about pronunciation.

---

## Where to hook in your code (exact touch points)

### 1) Modify `voice-capture.transcribe_file()` to return segments

Add to return tuple:

- `segments_out = [{"start": s.start, "end": s.end, "text": s.text}]`

So your frontend can display segments and your scoring can use them.

### 2) Add new script `scripts/pron_score.py`

CLI examples:

- `pron-score audio.wav --text "..." --out json`
- or read transcript from stdin:
  - `voice-capture foo.wav --text raw | pron-score foo.wav`

Better: accept your existing `voice-capture --text json` output to avoid mismatch.

### 3) Extend your frontend API pipeline

When you receive audio:

1. run `voice-capture` (or imported `transcribe_file`)
2. run `pron_score(audio, transcript)`
3. run `teach(transcript + score_summary)` or pass as separate field

---

## Concrete “MVP first” decision (what I’d do in your repo)

Given your current setup and desire for a “middle layer”:

### MVP (2–3 days)

- Whisper segments + WhisperX word timestamps
- Word-level risk scoring
- UI highlighting + click-to-replay
- LLM prompt uses risk list: “focus pronunciation tips on these words”

### v2 (after MVP works)

- MFA phone alignment
- wav2vec2 posterior scoring
- phone confusion hints

---

## Data model additions (Pydantic)

Add a model that matches the middle layer output:

```py
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

class PronScoreOut(BaseModel):
    audio: str
    overall_score: float
    overall_risk: str
    words: List[WordScore]
```

Then your `TeachOut` can optionally include `pronunciation` derived from it.

---

## Thresholding (simple, robust)

Use speaker-relative thresholds to avoid punishing naturally fast/slow speakers:

- compute median word score over utterance
- flag high risk if `score < (median - k*mad)` or below absolute floor like `0.45`
- always ignore words shorter than X ms (e.g. < 80ms) because alignment is unreliable

---

## If you want one “best path” choice

If you want the most direct route to **phoneme scoring** without weeks of research:

- **MFA for phone boundaries**
- **wav2vec2 CTC posteriors for phone scoring**
- map phone confusions to cues

That’s the cleanest separation of concerns: alignment and scoring are independent.

---

If you want, I can write the skeleton `scripts/pron_score.py` (CLI + Pydantic output + temp dir handling) in your repo style (dotenv, spinner, Colors) and leave TODO hooks where you plug in whisperx/MFA.
