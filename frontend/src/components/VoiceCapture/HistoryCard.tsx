import { useCallback, useEffect, useMemo, useState } from "react";
import type { Transcript } from "./types";
import { Card, Label } from "./ui";

type TeacherReply = {
  id: number;
  created_at: string;
  chat_key: string;
  mode: string;
  input_text: string;
  output: Record<string, unknown>;
};

type Tab = "transcripts" | "teacher";

async function readJson<T>(resp: Response): Promise<T> {
  return (await resp.json()) as T;
}

export function HistoryCard(props: { history: Transcript[] }) {
  const [tab, setTab] = useState<Tab>("transcripts");
  const [teacher, setTeacher] = useState<TeacherReply[]>([]);
  const [loadingTeacher, setLoadingTeacher] = useState(false);

  const refreshTeacher = useCallback(async () => {
    setLoadingTeacher(true);
    try {
      const res = await fetch("/api/english/history?limit=25");
      if (!res.ok) return;
      const data = await readJson<TeacherReply[]>(res);
      setTeacher(data);
    } finally {
      setLoadingTeacher(false);
    }
  }, []);

  useEffect(() => {
    if (tab === "teacher" && teacher.length === 0) {
      refreshTeacher().catch(() => {});
    }
  }, [tab, teacher.length, refreshTeacher]);

  const right = useMemo(() => {
    return (
      <div className="flex items-center gap-2">
        <button
          onClick={() => setTab("transcripts")}
          className={
            tab === "transcripts"
              ? "rounded-lg bg-zinc-900 px-3 py-2 text-sm font-medium text-white dark:bg-zinc-100 dark:text-zinc-900"
              : "rounded-lg border border-zinc-200 px-3 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900"
          }
        >
          Transcripts
        </button>

        <button
          onClick={() => {
            setTab("teacher");
            refreshTeacher().catch(() => {});
          }}
          className={
            tab === "teacher"
              ? "rounded-lg bg-zinc-900 px-3 py-2 text-sm font-medium text-white dark:bg-zinc-100 dark:text-zinc-900"
              : "rounded-lg border border-zinc-200 px-3 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900"
          }
        >
          Teacher
        </button>
      </div>
    );
  }, [tab, refreshTeacher]);

  return (
    <Card title="History" right={right}>
      {tab === "transcripts" ? (
        props.history.length === 0 ? (
          <div className="text-sm text-zinc-600 dark:text-zinc-400">
            No transcripts yet.
          </div>
        ) : (
          <div className="divide-y divide-zinc-200 dark:divide-zinc-800">
            {props.history.map((t) => {
              const dt = new Date(t.created_at);
              return (
                <div key={t.id} className="py-3">
                  <div className="text-xs text-zinc-500 dark:text-zinc-400">
                    #{t.id} — {dt.toLocaleString()} — {t.source}
                  </div>

                  <div className="mt-2">
                    <Label>Raw</Label>
                    <div className="mt-1 text-sm text-zinc-900 dark:text-zinc-100">
                      {t.raw_text}
                    </div>
                  </div>

                  <div className="mt-2">
                    <Label>Literal</Label>
                    <div className="mt-1 text-sm text-zinc-900 dark:text-zinc-100">
                      {t.literal_text}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )
      ) : loadingTeacher ? (
        <div className="text-sm text-zinc-600 dark:text-zinc-400">
          Loading teacher history…
        </div>
      ) : teacher.length === 0 ? (
        <div className="text-sm text-zinc-600 dark:text-zinc-400">
          No teacher replies yet.
        </div>
      ) : (
        <div className="divide-y divide-zinc-200 dark:divide-zinc-800">
          {teacher.map((r) => {
            const dt = new Date(r.created_at);
            const output = r.output;
            const replyText =
              typeof output?.reply === "string" ? output.reply : "";
            const corrected =
              typeof output?.corrected_natural === "string"
                ? output.corrected_natural
                : "";

            return (
              <div key={r.id} className="py-3">
                <div className="text-xs text-zinc-500 dark:text-zinc-400">
                  #{r.id} — {dt.toLocaleString()} — {r.mode} — {r.chat_key}
                </div>

                <div className="mt-2">
                  <Label>Input</Label>
                  <div className="mt-1 whitespace-pre-wrap text-sm text-zinc-900 dark:text-zinc-100">
                    {r.input_text}
                  </div>
                </div>

                {(corrected || replyText) && (
                  <div className="mt-2">
                    <Label>Teacher</Label>
                    <div className="mt-1 whitespace-pre-wrap text-sm text-zinc-900 dark:text-zinc-100">
                      {corrected ? `Corrected: ${corrected}\n\n` : ""}
                      {replyText ? `Reply: ${replyText}` : ""}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
