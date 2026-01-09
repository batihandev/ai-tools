import { Card, Label, Tooltip } from "./ui";

export function CaptureCard(props: {
  isListening: boolean;
  status: string;
  statusPillClass: string;

  showAdvanced: boolean;
  setShowAdvanced(v: boolean): void;

  silenceMs: number;
  setSilenceMs(ms: number): void;

  threshold: number;
  setThreshold(v: number): void;

  rmsTooltip: string;

  startListening(): Promise<void>;
  stopAll(): void;
  refreshHistory(): Promise<void>;
  resetDefaults(): void;
}) {
  return (
    <Card
      title="Capture"
      right={
        <button
          onClick={() => props.setShowAdvanced(!props.showAdvanced)}
          className="rounded-lg border border-zinc-200 px-3 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900"
        >
          {props.showAdvanced ? "Hide advanced" : "Advanced"}
        </button>
      }
    >
      {/* Center controls */}
      <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-900/30">
        <span
          className={`rounded-full border px-3 py-1 text-xs ${props.statusPillClass}`}
        >
          {props.status}
        </span>

        <div className="flex items-center gap-2">
          {!props.isListening ? (
            <button
              onClick={props.startListening}
              className="rounded-lg bg-zinc-900 px-5 py-2 text-sm font-medium text-white hover:bg-zinc-800 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-200"
            >
              Start
            </button>
          ) : (
            <button
              onClick={props.stopAll}
              className="rounded-lg bg-zinc-200 px-5 py-2 text-sm font-medium text-zinc-900 hover:bg-zinc-300 dark:bg-zinc-800 dark:text-zinc-100 dark:hover:bg-zinc-700"
            >
              Stop
            </button>
          )}

          <button
            onClick={props.refreshHistory}
            className="rounded-lg border border-zinc-200 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Advanced tuning */}
      {props.showAdvanced && (
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <div>
            <Label>Silence window</Label>
            <input
              type="range"
              min={400}
              max={2200}
              value={props.silenceMs}
              onChange={(e) => props.setSilenceMs(Number(e.target.value))}
              className="mt-2 w-full"
            />
            <div className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
              {props.silenceMs} ms
            </div>
          </div>

          <div>
            <div className="flex items-center">
              <Label>Voice threshold (RMS)</Label>
              <Tooltip text={props.rmsTooltip} />
            </div>

            <input
              type="range"
              min={0.006}
              max={0.05}
              step={0.001}
              value={props.threshold}
              onChange={(e) => props.setThreshold(Number(e.target.value))}
              className="mt-2 w-full"
            />

            <div className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
              {props.threshold.toFixed(3)} (higher = less sensitive)
            </div>

            <div className="mt-2">
              <button
                onClick={props.resetDefaults}
                className="rounded-lg border border-zinc-200 px-3 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900"
              >
                Reset defaults
              </button>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}
