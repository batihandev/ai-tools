import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { LatestResult, Transcript } from "./types";

function clamp(n: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, n));
}

const DEFAULT_SILENCE_MS = 850;
const DEFAULT_THRESHOLD = 0.014;

export type VoiceCaptureState = {
  // UI state
  isListening: boolean;
  status: string;
  showAdvanced: boolean;

  // knobs
  silenceMs: number;
  threshold: number;

  // data
  latest: LatestResult | null;
  history: Transcript[];

  // helpers
  statusPillClass: string;
  rmsTooltip: string;

  // actions
  setShowAdvanced(v: boolean): void;
  setSilenceMs(ms: number): void;
  setThreshold(v: number): void;
  resetDefaults(): void;

  startListening(): Promise<void>;
  stopAll(): void;
  refreshHistory(): Promise<void>;
};

type UseVoiceCaptureOpts = {
  onNewTranscript?: (t: LatestResult) => void;
};

async function readJson<T>(resp: Response): Promise<T> {
  return (await resp.json()) as T;
}

type TranscribeApiOk = {
  id: number;
  raw_text: string;
  literal_text: string;
};

type ApiErr = { detail?: string };

export function useVoiceCapture(opts?: UseVoiceCaptureOpts): VoiceCaptureState {
  const [isListening, setIsListening] = useState(false);
  const [status, setStatus] = useState("Idle");
  const [latest, setLatest] = useState<LatestResult | null>(null);
  const [history, setHistory] = useState<Transcript[]>([]);

  const [showAdvanced, setShowAdvanced] = useState(false);
  const [silenceMs, _setSilenceMs] = useState(DEFAULT_SILENCE_MS);
  const [threshold, _setThreshold] = useState(DEFAULT_THRESHOLD);

  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);

  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const dataRef = useRef<Float32Array<ArrayBuffer> | null>(null);
  const sawVoiceRef = useRef(false);

  const lastVoiceAtRef = useRef<number>(0);
  const rafRef = useRef<number | null>(null);

  // Avoid stale closures for listening state + callback
  const isListeningRef = useRef(false);
  useEffect(() => {
    isListeningRef.current = isListening;
  }, [isListening]);

  const onNewTranscriptRef = useRef<UseVoiceCaptureOpts["onNewTranscript"]>(
    opts?.onNewTranscript,
  );
  useEffect(() => {
    onNewTranscriptRef.current = opts?.onNewTranscript;
  }, [opts?.onNewTranscript]);

  const setSilenceMs = useCallback((ms: number) => {
    _setSilenceMs(clamp(ms, 400, 2200));
  }, []);

  const setThreshold = useCallback((v: number) => {
    _setThreshold(v);
  }, []);

  const resetDefaults = useCallback(() => {
    _setSilenceMs(DEFAULT_SILENCE_MS);
    _setThreshold(DEFAULT_THRESHOLD);
  }, []);

  const refreshHistory = useCallback(async () => {
    const res = await fetch("/api/transcripts?limit=25");
    if (!res.ok) return;
    const data = (await res.json()) as Transcript[];
    setHistory(data);
  }, []);

  useEffect(() => {
    refreshHistory().catch(() => {});
  }, [refreshHistory]);

  const uploadUtterance = useCallback(
    async (blob: Blob) => {
      setStatus("Uploading…");

      const file = new File([blob], "utterance.webm", {
        type: blob.type || "audio/webm",
      });

      const form = new FormData();
      form.append("audio", file);

      const resp = await fetch("/api/voice/transcribe", {
        method: "POST",
        body: form,
      });

      if (!resp.ok) {
        const err = await readJson<ApiErr>(resp).catch((): ApiErr => ({}));
        const detail = err?.detail ?? `HTTP ${resp.status}`;
        console.error("Transcribe API error:", detail);
        setStatus(`Error: ${detail}`);
        throw new Error(detail);
      }

      const out = await readJson<TranscribeApiOk>(resp);

      const t: LatestResult = {
        id: out.id,
        raw_text: out.raw_text ?? "",
        literal_text: out.literal_text ?? "",
      };

      // IMPORTANT: use the ref, not opts directly
      onNewTranscriptRef.current?.(t);

      setLatest(t);
      setStatus("Done");

      // If still listening, return to "Listening…" without flicker
      if (isListeningRef.current) {
        window.setTimeout(() => {
          if (isListeningRef.current) setStatus("Listening…");
        }, 250);
      }

      await refreshHistory();
    },
    [refreshHistory],
  );

  const startNewRecorder = useCallback(() => {
    if (!streamRef.current) return;

    chunksRef.current = [];
    sawVoiceRef.current = false;

    let recorder: MediaRecorder;
    try {
      recorder = new MediaRecorder(streamRef.current, {
        mimeType: "audio/webm",
      });
    } catch {
      recorder = new MediaRecorder(streamRef.current);
    }

    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
    };

    recorder.onerror = (e) => {
      console.error("MediaRecorder error:", e);
      setStatus("Error: recorder failed");
    };

    recorder.onstop = async () => {
      const blob = new Blob(chunksRef.current, {
        type: recorder.mimeType || "audio/webm",
      });
      chunksRef.current = [];

      // Ignore accidental ultra-short chunks (common on stop/start)
      if (blob.size < 4096) {
        console.log(`Skipping tiny blob: ${blob.size} bytes`);
        if (isListeningRef.current) startNewRecorder();
        return;
      }

      if (!sawVoiceRef.current) {
        console.log("Skipping upload: no speech detected in this chunk");
        if (isListeningRef.current) startNewRecorder();
        else setStatus("Idle (no speech detected)");
        return;
      }

      // Log blob info for debugging
      console.log(
        `Processing audio blob: ${blob.size} bytes, type: ${blob.type}`,
      );

      try {
        await uploadUtterance(blob);
      } catch (err) {
        console.error("Upload failed:", err);
        setStatus(
          `Error: ${err instanceof Error ? err.message : "Upload failed"}`,
        );
      } finally {
        if (isListeningRef.current) startNewRecorder();
      }
    };

    recorderRef.current = recorder;

    // Wait a tick to ensure stream is fully ready
    setTimeout(() => {
      if (recorder.state === "inactive") {
        recorder.start(250);
      }
    }, 50);
  }, [uploadUtterance]);

  const loopVAD = useCallback(() => {
    const analyser = analyserRef.current;
    const data = dataRef.current;
    const recorder = recorderRef.current;

    if (!analyser || !data || !recorder || !isListeningRef.current) return;

    analyser.getFloatTimeDomainData(data);

    let sum = 0;
    for (let i = 0; i < data.length; i++) {
      const v = data[i];
      sum += v * v;
    }
    const rms = Math.sqrt(sum / data.length);

    const now = performance.now();
    if (rms >= threshold) {
      lastVoiceAtRef.current = now;
      sawVoiceRef.current = true;
    }

    const lastVoiceAt = lastVoiceAtRef.current;
    if (lastVoiceAt > 0 && now - lastVoiceAt > silenceMs) {
      lastVoiceAtRef.current = 0;

      if (recorder.state !== "inactive") {
        setStatus("Silence detected → transcribing…");
        try {
          recorder.requestData();
        } catch {
          // ignore
        }
        recorder.stop();
      }
    }

    rafRef.current = requestAnimationFrame(loopVAD);
  }, [silenceMs, threshold]);

  const startListening = useCallback(async () => {
    setStatus("Requesting microphone…");
    setLatest(null);

    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    streamRef.current = stream;

    const audioCtx = new AudioContext();
    audioCtxRef.current = audioCtx;

    const source = audioCtx.createMediaStreamSource(stream);
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 2048;

    source.connect(analyser);
    analyserRef.current = analyser;

    // FIX: correct typing (no generics)
    dataRef.current = new Float32Array(analyser.fftSize);

    lastVoiceAtRef.current = 0;

    setIsListening(true);
    isListeningRef.current = true;
    setStatus("Listening…");

    startNewRecorder();
    rafRef.current = requestAnimationFrame(loopVAD);
  }, [loopVAD, startNewRecorder]);

  const stopAll = useCallback(() => {
    setIsListening(false);
    isListeningRef.current = false;
    setStatus("Idle");

    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }

    const rec = recorderRef.current;
    if (rec && rec.state !== "inactive") {
      try {
        rec.requestData();
      } catch {
        // ignore
      }
      rec.stop();
    }
    recorderRef.current = null;
    chunksRef.current = [];

    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }

    if (audioCtxRef.current) {
      audioCtxRef.current.close().catch(() => {});
      audioCtxRef.current = null;
    }

    analyserRef.current = null;
    dataRef.current = null;
  }, []);

  useEffect(() => {
    return () => stopAll();
  }, [stopAll]);

  const statusPillClass = status.startsWith("Error")
    ? "bg-red-500/10 text-red-300 border-red-500/20"
    : "bg-emerald-500/10 text-emerald-300 border-emerald-500/20";

  const rmsTooltip = useMemo(
    () =>
      [
        "RMS is the average signal power (volume) over a short window.",
        "",
        "Higher threshold = less sensitive:",
        "- Ignores more background noise",
        "- May miss quiet speech",
        "",
        "Lower threshold = more sensitive:",
        "- Captures quieter speech",
        "- More likely to trigger on noise",
      ].join("\n"),
    [],
  );

  return {
    isListening,
    status,
    showAdvanced,
    silenceMs,
    threshold,
    latest,
    history,
    statusPillClass,
    rmsTooltip,
    setShowAdvanced,
    setSilenceMs,
    setThreshold,
    resetDefaults,
    startListening,
    stopAll,
    refreshHistory,
  };
}
