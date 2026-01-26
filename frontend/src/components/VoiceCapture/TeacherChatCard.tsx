import { useEffect, useRef, useState } from "react";
import type { ChatMsg, TeacherMode } from "./useTeacherChat";
import { Card } from "./ui";
import { ModeIndicator } from "./ModeIndicator";

export function TeacherChatCard(props: {
  messages: ChatMsg[];
  aiTyping: boolean;
  currentMode: TeacherMode;
  onModeSettingsClick: () => void;
  onClear(): void;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [unloading, setUnloading] = useState(false);

  // Auto-scroll to bottom when messages change or aiTyping toggles on.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [props.messages.length, props.aiTyping]);

  const handleUnload = async () => {
    setUnloading(true);
    try {
      const resp = await fetch("/api/omni/unload", { method: "DELETE" });
      const data = await resp.json();
      alert(data.message || "Model unloaded");
    } catch {
      alert("Failed to unload model");
    } finally {
      setUnloading(false);
    }
  };

  return (
    <Card
      title="Session"
      right={
        <div className="flex items-center gap-2">
          <ModeIndicator
            currentMode={props.currentMode}
            onClick={props.onModeSettingsClick}
          />
          <button
            onClick={handleUnload}
            disabled={unloading}
            className="rounded-lg border border-red-500/30 px-3 py-2 text-sm font-medium text-red-400 hover:bg-red-500/10 disabled:opacity-50 dark:border-red-500/30 dark:text-red-400"
            title="Unload model to free VRAM"
          >
            {unloading ? "..." : "Unload"}
          </button>
          <button
            onClick={props.onClear}
            className="rounded-lg border border-zinc-200 px-3 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900"
          >
            Clear
          </button>
        </div>
      }
    >
      <div
        ref={scrollRef}
        className="max-h-105 overflow-auto rounded-lg border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-800 dark:bg-zinc-900/30"
      >
        {props.messages.length === 0 ? (
          <div className="text-sm text-zinc-600 dark:text-zinc-400">
            Speak to start a session. Your transcripts and the teacher’s replies
            will appear here.
          </div>
        ) : (
          <div className="space-y-3">
            {props.messages.map((m) => (
              <div
                key={m.id}
                className={
                  m.role === "user" ? "flex justify-end" : "flex justify-start"
                }
              >
                <div
                  className={
                    m.role === "user"
                      ? "max-w-[85%] whitespace-pre-wrap rounded-2xl bg-zinc-900 px-3 py-2 text-sm text-white dark:bg-zinc-100 dark:text-zinc-900"
                      : "max-w-[85%] whitespace-pre-wrap rounded-2xl border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-900 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-100"
                  }
                >
                  {m.text}
                  {m.role === "assistant" && m.audio_path && (
                    <div className="mt-2">
                      <audio
                        controls
                        src={m.audio_path}
                        className="h-8 w-full max-w-[200px]"
                      />
                    </div>
                  )}
                </div>
              </div>
            ))}

            {props.aiTyping && (
              <div className="flex justify-start">
                <div className="rounded-2xl border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-600 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300">
                  Teacher is typing…
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
