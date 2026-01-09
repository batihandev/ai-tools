import type { LatestResult } from "./types";
import { Card, Label, PreBox } from "./ui";

export function LatestTranscriptCard(props: { latest: LatestResult | null }) {
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
        </div>
      )}
    </Card>
  );
}
