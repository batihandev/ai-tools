import { useCallback, useEffect, useMemo, useRef, useState } from "react";

export type ChatMsg =
  | { id: string; role: "user"; text: string; ts: number }
  | {
      id: string;
      role: "assistant";
      text: string;
      ts: number;
      audio_path?: string;
    };

export type TeacherMode = "coach" | "strict" | "correct";

type TeachOut = {
  corrected_natural: string;
  corrected_literal: string;
  mistakes: Array<{ frm: string; to: string; why: string }>;
  pronunciation: Array<{ word: string; ipa: string; cue: string }>;
  reply: string;
  follow_up_question: string;
  raw_error?: boolean;
  raw_output?: string;
  audio_path?: string;
};

type ApiError = { detail?: string };

type ChatGetOut = {
  chat_key: string;
  updated_at: string;
  messages: Array<{
    id: string;
    role: "user" | "assistant";
    text: string;
    ts?: number;
    audio_path?: string;
  }>;
};

async function readJson<T>(resp: Response): Promise<T> {
  return (await resp.json()) as T;
}

function uid(prefix: string) {
  return `${prefix}_${Math.random().toString(16).slice(2)}_${Date.now()}`;
}

function nowTs() {
  return Date.now();
}

function newChatKey() {
  return `chat_${crypto.randomUUID()}`;
}

function getChatKey() {
  const k = localStorage.getItem("ai_scripts_chat_key");
  if (k) return k;
  const nk = newChatKey();
  localStorage.setItem("ai_scripts_chat_key", nk);
  return nk;
}

function setChatKey(k: string) {
  localStorage.setItem("ai_scripts_chat_key", k);
}

export function useTeacherChat(opts?: {
  initialMode?: TeacherMode;
  autoLoad?: boolean; // default true
}) {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [aiStatus, setAiStatus] = useState<"idle" | "waiting">("idle");
  const [mode, setMode] = useState<TeacherMode>(opts?.initialMode ?? "coach");

  const [chatKey, setChatKeyState] = useState(() => getChatKey());

  // buffer of user text that has NOT been sent to AI yet (while waiting, or before first send)
  const pendingRef = useRef<string[]>([]);
  const inFlightRef = useRef(false);

  // debounce saving chat state to DB
  const saveTimerRef = useRef<number | null>(null);

  const scheduleSave = useCallback(
    (next: ChatMsg[]) => {
      if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = window.setTimeout(async () => {
        try {
          await fetch("/api/chat/save", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ chat_key: chatKey, messages: next }),
          });
        } catch {
          // ignore
        }
      }, 600);
    },
    [chatKey],
  );

  const setMessagesAndSave = useCallback(
    (updater: (prev: ChatMsg[]) => ChatMsg[]) => {
      setMessages((prev) => {
        const next = updater(prev);
        scheduleSave(next);
        return next;
      });
    },
    [scheduleSave],
  );

  // Optional: load existing chat state on mount (or when key changes)
  useEffect(() => {
    const autoLoad = opts?.autoLoad ?? true;
    if (!autoLoad) return;

    let cancelled = false;

    (async () => {
      try {
        const resp = await fetch(
          `/api/chat/get?chat_key=${encodeURIComponent(chatKey)}`,
        );
        if (!resp.ok) return;
        const out = await readJson<ChatGetOut>(resp);
        if (cancelled) return;

        const loaded: ChatMsg[] = (out.messages ?? []).map((m) => ({
          id: m.id,
          role: m.role,
          text: m.text,
          ts: typeof m.ts === "number" ? m.ts : nowTs(),
          audio_path:
            m.role === "assistant" ? (m as any).audio_path : undefined,
        }));
        setMessages(loaded);
      } catch {
        // ignore (chat not found is fine)
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [chatKey, opts?.autoLoad]);

  const appendUser = useCallback(
    (text: string) => {
      const t = text.trim();
      if (!t) return;

      setMessagesAndSave((prev) => [
        ...prev,
        { id: uid("u"), role: "user", text: t, ts: nowTs() },
      ]);

      pendingRef.current.push(t);
    },
    [setMessagesAndSave],
  );

  const formatAiMessage = useCallback((out: TeachOut) => {
    if (out.raw_error) {
      // if teacher failed JSON, show raw output if present
      return (
        (out.raw_output || "").trim() || "Teacher response was not valid JSON."
      );
    }

    const lines: string[] = [];

    if (out.corrected_natural) {
      lines.push(`Corrected (natural): ${out.corrected_natural}`);
    }
    if (out.corrected_literal) {
      lines.push(`Corrected (literal): ${out.corrected_literal}`);
    }

    if (out.mistakes?.length) {
      lines.push("");
      lines.push("Mistakes:");
      for (const m of out.mistakes.slice(0, 6)) {
        lines.push(`- "${m.frm}" → "${m.to}" (${m.why})`);
      }
    }

    if (out.pronunciation?.length) {
      lines.push("");
      lines.push("Pronunciation:");
      for (const p of out.pronunciation.slice(0, 5)) {
        const ipa = p.ipa ? `/${p.ipa}/` : "";
        lines.push(`- ${p.word} ${ipa} — ${p.cue}`.trim());
      }
    }

    if (out.reply) {
      lines.push("");
      lines.push(`Reply: ${out.reply}`);
    }
    if (out.follow_up_question) {
      lines.push(`Follow-up: ${out.follow_up_question}`);
    }

    return lines.join("\n").trim();
  }, []);

  const flushIfPossible = useCallback(async () => {
    if (inFlightRef.current) return;
    if (pendingRef.current.length === 0) return;

    inFlightRef.current = true;
    setAiStatus("waiting");

    // combine pending into one batch
    const batch = pendingRef.current.join("\n");
    pendingRef.current = [];

    try {
      const resp = await fetch("/api/english/teach", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: batch,
          mode,
          chat_key: chatKey,
        }),
      });

      if (!resp.ok) {
        const err = await readJson<ApiError>(resp);
        const detail = err?.detail ?? `HTTP ${resp.status}`;
        setMessagesAndSave((prev) => [
          ...prev,
          {
            id: uid("a"),
            role: "assistant",
            text: `Error: ${detail}`,
            ts: nowTs(),
          },
        ]);
        return;
      }

      const out = await readJson<TeachOut>(resp);
      const msg = formatAiMessage(out);

      setMessagesAndSave((prev) => [
        ...prev,
        {
          id: uid("a"),
          role: "assistant",
          text: msg,
          ts: nowTs(),
          audio_path: out.audio_path,
        },
      ]);
    } catch (e) {
      console.error("Teacher chat error:", e);
      setMessagesAndSave((prev) => [
        ...prev,
        {
          id: uid("a"),
          role: "assistant",
          text: `Error: request failed`,
          ts: nowTs(),
        },
      ]);
    } finally {
      inFlightRef.current = false;
      setAiStatus("idle");

      // If user kept talking while we waited, send the next combined batch immediately.
      if (pendingRef.current.length > 0) {
        Promise.resolve().then(() => flushIfPossible());
      }
    }
  }, [chatKey, mode, formatAiMessage, setMessagesAndSave]);

  const onTranscript = useCallback(
    (rawText: string) => {
      appendUser(rawText);

      // If AI is idle, send now; otherwise it will stay in pending buffer
      if (!inFlightRef.current) {
        flushIfPossible().catch(() => {});
      }
    },
    [appendUser, flushIfPossible],
  );

  const aiTyping = useMemo(() => aiStatus === "waiting", [aiStatus]);

  const clear = useCallback(() => {
    // new session key
    const nk = newChatKey();
    setChatKey(nk);
    setChatKeyState(nk);

    // reset local state/buffers
    setMessages([]);
    pendingRef.current = [];
    setAiStatus("idle");
    inFlightRef.current = false;

    // write empty chat state for new key (best-effort)
    fetch("/api/chat/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_key: nk, messages: [] }),
    }).catch(() => {});
  }, []);

  return {
    chatKey,
    mode,
    setMode,
    messages,
    aiTyping,
    onTranscript,
    clear,
    flushIfPossible, // optional: expose for manual trigger
  };
}
