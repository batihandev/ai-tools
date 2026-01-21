import { useEffect, useState } from "react";
import type { TeacherMode } from "./useTeacherChat";

export interface ModeInfo {
  name: string;
  description: string;
}

interface ModeSettingsModalProps {
  isOpen: boolean;
  currentMode: TeacherMode;
  onModeChange: (mode: TeacherMode) => void;
  onClose: () => void;
}

export function ModeSettingsModal({
  isOpen,
  currentMode,
  onModeChange,
  onClose,
}: ModeSettingsModalProps) {
  const [modes, setModes] = useState<ModeInfo[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!isOpen) return;

    const controller = new AbortController();
    let isActive = true;

    queueMicrotask(() => {
      if (!isActive) return;
      setLoading(true);
    });

    fetch("/api/english/modes", { signal: controller.signal })
      .then((resp) => resp.json())
      .then((data: ModeInfo[]) => {
        if (!isActive) return;
        setModes(data);
      })
      .catch((err) => {
        if (!isActive) return;
        if ((err as { name?: string } | null)?.name === "AbortError") return;
        setModes([]);
      })
      .finally(() => {
        if (!isActive) return;
        setLoading(false);
      });

    return () => {
      isActive = false;
      controller.abort();
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const getModeColor = (mode: string) => {
    switch (mode) {
      case "coach":
        return "bg-blue-50 border-blue-200 dark:bg-blue-950/30 dark:border-blue-800";
      case "strict":
        return "bg-amber-50 border-amber-200 dark:bg-amber-950/30 dark:border-amber-800";
      case "correct":
        return "bg-green-50 border-green-200 dark:bg-green-950/30 dark:border-green-800";
      default:
        return "bg-zinc-50 border-zinc-200 dark:bg-zinc-900/30 dark:border-zinc-800";
    }
  };

  const getModeTextColor = (mode: string) => {
    switch (mode) {
      case "coach":
        return "text-blue-900 dark:text-blue-100";
      case "strict":
        return "text-amber-900 dark:text-amber-100";
      case "correct":
        return "text-green-900 dark:text-green-100";
      default:
        return "text-zinc-900 dark:text-zinc-100";
    }
  };

  const getBadgeColor = (mode: string) => {
    switch (mode) {
      case "coach":
        return "bg-blue-500 text-white";
      case "strict":
        return "bg-amber-500 text-white";
      case "correct":
        return "bg-green-500 text-white";
      default:
        return "bg-zinc-500 text-white";
    }
  };

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        className="fixed inset-0 z-40 bg-black/30 backdrop-blur-sm"
      />

      {/* Modal */}
      <div className="fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-full max-w-md -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-lg border border-zinc-200 bg-white shadow-lg dark:border-zinc-800 dark:bg-zinc-950">
        {/* Header */}
        <div className="sticky top-0 border-b border-zinc-200 bg-white px-6 py-4 dark:border-zinc-800 dark:bg-zinc-950">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
              Teacher Mode
            </h2>
            <button
              onClick={onClose}
              className="rounded-lg p-1 text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-900"
            >
              ✕
            </button>
          </div>
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
            Select how the teacher responds to your corrections.
          </p>
        </div>

        {/* Content */}
        <div className="px-6 py-4">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <div className="text-sm text-zinc-600 dark:text-zinc-400">
                Loading modes…
              </div>
            </div>
          ) : modes.length === 0 ? (
            <div className="py-8 text-center text-sm text-zinc-600 dark:text-zinc-400">
              Unable to load modes
            </div>
          ) : (
            <div className="space-y-3">
              {modes.map((mode) => (
                <button
                  key={mode.name}
                  onClick={() => {
                    onModeChange(mode.name as TeacherMode);
                    onClose();
                  }}
                  className={`w-full text-left rounded-lg border-2 px-4 py-3 transition-all ${
                    currentMode === mode.name
                      ? `border-zinc-900 bg-zinc-900 text-white dark:border-zinc-100 dark:bg-zinc-100 dark:text-zinc-900`
                      : getModeColor(mode.name)
                  }`}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div
                        className={`mb-1 flex items-center gap-2 font-semibold capitalize ${
                          currentMode === mode.name
                            ? "text-white dark:text-zinc-900"
                            : getModeTextColor(mode.name)
                        }`}
                      >
                        {mode.name}
                        {currentMode === mode.name && (
                          <span
                            className={`inline-block rounded px-2 py-1 text-xs font-bold ${getBadgeColor(mode.name)}`}
                          >
                            Current
                          </span>
                        )}
                      </div>
                      <p
                        className={`text-xs leading-relaxed ${
                          currentMode === mode.name
                            ? "text-zinc-200 dark:text-zinc-800"
                            : "text-zinc-700 dark:text-zinc-300"
                        }`}
                      >
                        {mode.description}
                      </p>
                    </div>
                    {currentMode === mode.name && (
                      <div className="ml-2 flex-shrink-0 text-lg">✓</div>
                    )}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-zinc-200 bg-zinc-50 px-6 py-3 dark:border-zinc-800 dark:bg-zinc-900/50">
          <button
            onClick={onClose}
            className="w-full rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-200"
          >
            Close
          </button>
        </div>
      </div>
    </>
  );
}
