import type { LatestResult } from "./types";
import { Card, Label, PreBox } from "./ui";

export function LatestTranscriptCard(props: {
  latest: LatestResult | null;
  onRetry?: (text: string) => void;
}) {
  return (
    <Card title="Latest transcript">
      {!props.latest ? (
        <div className="text-sm text-zinc-600 dark:text-zinc-400">
          No transcript yet.
        </div>
      ) : (
        <div className="grid gap-4">
          <div>
            <Label>Raw</Label>
            <div className="mt-2">
              <PreBox>{props.latest.raw_text}</PreBox>
            </div>
          </div>
          <div>
            <Label>Literal</Label>
            <div className="mt-2">
              <PreBox>{props.latest.literal_text}</PreBox>
            </div>
          </div>

          {props.onRetry && props.latest.raw_text.trim() && (
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => props.onRetry?.(props.latest?.raw_text ?? "")}
                className="rounded-lg border border-zinc-200 px-3 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900"
              >
                Retry send to teacher
              </button>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
