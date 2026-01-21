import type { TeacherMode } from "./useTeacherChat";

interface ModeIndicatorProps {
  currentMode: TeacherMode;
  onClick: () => void;
}

export function ModeIndicator({ currentMode, onClick }: ModeIndicatorProps) {
  const getModeColor = (mode: string) => {
    switch (mode) {
      case "coach":
        return "bg-blue-100 text-blue-800 border-blue-300 hover:bg-blue-200 dark:bg-blue-950 dark:text-blue-300 dark:border-blue-700 dark:hover:bg-blue-900";
      case "strict":
        return "bg-amber-100 text-amber-800 border-amber-300 hover:bg-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-700 dark:hover:bg-amber-900";
      case "correct":
        return "bg-green-100 text-green-800 border-green-300 hover:bg-green-200 dark:bg-green-950 dark:text-green-300 dark:border-green-700 dark:hover:bg-green-900";
      default:
        return "bg-zinc-100 text-zinc-800 border-zinc-300 hover:bg-zinc-200 dark:bg-zinc-900 dark:text-zinc-300 dark:border-zinc-700 dark:hover:bg-zinc-800";
    }
  };

  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold capitalize transition-colors ${getModeColor(currentMode)}`}
      title={`Current mode: ${currentMode}. Click to change.`}
    >
      <span className="inline-block h-2 w-2 rounded-full bg-current opacity-75" />
      {currentMode}
      <span className="text-current opacity-60">⚙</span>
    </button>
  );
}
