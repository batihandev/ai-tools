import type { LatestResult, WordScore } from "./types";
import { useRef, useState, useEffect } from "react";

// Simple browser TTS fallback
function speakWordBrowser(word: string) {
  if ("speechSynthesis" in window) {
    const utterance = new SpeechSynthesisUtterance(word);
    utterance.lang = "en-US";
    utterance.rate = 0.8;
    speechSynthesis.speak(utterance);
  }
}

// Edge TTS via API
async function speakWordAPI(word: string): Promise<void> {
  try {
    const resp = await fetch("/api/tts/pronounce", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ word, accent: "us" }),
    });
    if (!resp.ok) throw new Error("TTS failed");
    const blob = await resp.blob();
    const audio = new Audio(URL.createObjectURL(blob));
    await new Promise<void>((resolve) => {
      audio.onended = () => resolve();
      audio.onerror = () => resolve();
      audio.play();
    });
  } catch {
    // Fallback to browser TTS
    speakWordBrowser(word);
  }
}

interface WordPopupProps {
  word: WordScore;
  onClose: () => void;
  pauseListening?: () => void;
  resumeListening?: () => void;
}

function WordPopup({
  word,
  onClose,
  pauseListening,
  resumeListening,
}: WordPopupProps) {
  const popupRef = useRef<HTMLDivElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);

  // Close on outside click
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (popupRef.current && !popupRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [onClose]);

  const handleListen = async () => {
    setIsPlaying(true);
    pauseListening?.();
    await speakWordAPI(word.word);
    setIsPlaying(false);
    // Delay resume to avoid capturing tail-end audio
    setTimeout(() => resumeListening?.(), 500);
  };

  const duration = (word.end - word.start).toFixed(2);
  const scorePercent = Math.round(word.score * 100);
  const fluencyPercent = word.fluency_score
    ? Math.round(word.fluency_score * 100)
    : null;

  return (
    <div
      ref={popupRef}
      className="fixed left-1/2 top-1/2 z-50 w-72 -translate-x-1/2 -translate-y-1/2 rounded-xl bg-zinc-900 p-4 text-white shadow-2xl dark:bg-zinc-800"
    >
      {/* Close button */}
      <button
        onClick={onClose}
        className="absolute right-2 top-2 text-zinc-400 hover:text-white"
      >
        ✕
      </button>

      {/* Word title */}
      <div className="text-center text-2xl font-bold">{word.word}</div>

      {/* Phonemes */}
      {word.expected_phonemes && word.expected_phonemes.length > 0 && (
        <div className="mt-2 text-center text-sm text-zinc-400">
          /{word.expected_phonemes.join(" ")}/
        </div>
      )}

      {/* Listen button */}
      <button
        onClick={handleListen}
        disabled={isPlaying}
        className="mt-4 w-full rounded-lg bg-blue-600 py-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-50"
      >
        {isPlaying ? "🔊 Playing..." : "🔊 Listen to pronunciation"}
      </button>

      {/* Stats */}
      <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-lg bg-zinc-800 p-2 text-center dark:bg-zinc-700">
          <div className="text-zinc-400">Score</div>
          <div className="text-lg font-bold">{scorePercent}%</div>
        </div>
        <div className="rounded-lg bg-zinc-800 p-2 text-center dark:bg-zinc-700">
          <div className="text-zinc-400">Duration</div>
          <div className="text-lg font-bold">{duration}s</div>
        </div>
        {fluencyPercent !== null && (
          <div className="rounded-lg bg-zinc-800 p-2 text-center dark:bg-zinc-700">
            <div className="text-zinc-400">Fluency</div>
            <div className="text-lg font-bold">{fluencyPercent}%</div>
          </div>
        )}
        <div
          className={`rounded-lg p-2 text-center ${
            word.risk === "high"
              ? "bg-red-900/50"
              : word.risk === "medium"
                ? "bg-yellow-900/50"
                : "bg-green-900/50"
          }`}
        >
          <div className="text-zinc-400">Risk</div>
          <div className="text-lg font-bold capitalize">{word.risk}</div>
        </div>
      </div>
    </div>
  );
}

export function LatestTranscriptCard({
  latest,
  audioBlob,
  onRetry,
  pauseListening,
  resumeListening,
}: {
  latest: LatestResult | null;
  audioBlob: Blob | null;
  onRetry?: (text: string) => void;
  pauseListening?: () => void;
  resumeListening?: () => void;
}) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [selectedWord, setSelectedWord] = useState<WordScore | null>(null);

  if (!latest) {
    return (
      <div className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
        <h3 className="mb-2 font-semibold text-zinc-900 dark:text-zinc-100">
          Latest transcript
        </h3>
        <p className="text-sm text-zinc-500 italic">No transcript yet.</p>
      </div>
    );
  }

  const togglePlay = () => {
    if (!audioBlob) return;
    if (!audioRef.current) {
      audioRef.current = new Audio(URL.createObjectURL(audioBlob));
      audioRef.current.onended = () => {
        setIsPlaying(false);
        setTimeout(() => resumeListening?.(), 500);
      };
    }

    if (isPlaying) {
      audioRef.current.pause();
      setIsPlaying(false);
      setTimeout(() => resumeListening?.(), 500);
    } else {
      pauseListening?.();
      audioRef.current.play().catch((e) => console.error("Play failed", e));
      setIsPlaying(true);
    }
  };

  const hasPron = latest.pronunciation && latest.pronunciation.words.length > 0;

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      {/* Popup overlay */}
      {selectedWord && (
        <WordPopup
          word={selectedWord}
          onClose={() => {
            setSelectedWord(null);
            setTimeout(() => resumeListening?.(), 500);
          }}
          pauseListening={pauseListening}
          resumeListening={resumeListening}
        />
      )}

      <div className="mb-4 flex items-center justify-between">
        <h3 className="font-semibold text-zinc-900 dark:text-zinc-100">
          Latest transcript
        </h3>
        {audioBlob && (
          <button
            onClick={togglePlay}
            className="rounded-md bg-zinc-100 px-3 py-1 text-xs font-medium text-zinc-700 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
          >
            {isPlaying ? "⏸ Stop" : "▶ Replay Audio"}
          </button>
        )}
      </div>

      <div className="space-y-4">
        {/* Pronunciation Analysis */}
        {hasPron && (
          <div>
            <h4 className="mb-1 text-xs font-bold uppercase tracking-wider text-zinc-400">
              Pronunciation Analysis
            </h4>
            <div className="rounded-lg bg-zinc-50 px-3 py-3 text-lg leading-relaxed dark:bg-zinc-950/50">
              {latest.pronunciation!.words.map((w, i) => {
                let colorClass = "text-zinc-900 dark:text-zinc-100";
                if (w.risk === "high")
                  colorClass =
                    "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300";
                else if (w.risk === "medium")
                  colorClass =
                    "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300";

                return (
                  <span
                    key={i}
                    onClick={() => setSelectedWord(w)}
                    className={`mr-1 inline-block cursor-pointer rounded px-0.5 transition-transform hover:scale-105 ${colorClass}`}
                  >
                    {w.word}
                  </span>
                );
              })}
            </div>
            <p className="mt-1 text-[10px] text-zinc-400">
              Click on words for details. Red = lower confidence/clarity.
            </p>
          </div>
        )}

        {/* Raw text */}
        {!hasPron && (
          <div>
            <h4 className="mb-1 text-xs font-bold uppercase tracking-wider text-zinc-400">
              Raw
            </h4>
            <div className="rounded-md bg-zinc-50 px-3 py-2 text-sm text-zinc-800 dark:bg-zinc-950/50 dark:text-zinc-200">
              {latest.raw_text || (
                <span className="text-zinc-400 italic">...</span>
              )}
            </div>
          </div>
        )}

        {/* Literal text */}
        <div>
          <h4 className="mb-1 text-xs font-bold uppercase tracking-wider text-zinc-400">
            Literal
          </h4>
          <div className="rounded-md bg-zinc-50 px-3 py-2 text-sm text-zinc-800 dark:bg-zinc-950/50 dark:text-zinc-200">
            {latest.literal_text || (
              <span className="text-zinc-400 italic">...</span>
            )}
          </div>
        </div>
      </div>

      {onRetry && (
        <div className="mt-4 flex justify-end">
          <button
            onClick={() => onRetry(latest.raw_text)}
            className="text-xs text-zinc-500 hover:text-zinc-700 hover:underline dark:hover:text-zinc-300"
          >
            Retry send to teacher
          </button>
        </div>
      )}
    </div>
  );
}
