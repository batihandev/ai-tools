import { type Theme, toggleTheme } from "../lib/theme";

export type NavKey = "voice" | "tools" | "settings";

export function Header(props: {
  active: NavKey;
  onNav: (k: NavKey) => void;
  theme: Theme;
  setTheme: (t: Theme) => void;
}) {
  const { active, onNav, theme, setTheme } = props;

  const linkClass = (k: NavKey) =>
    [
      "px-3 py-2 rounded-md text-sm font-medium transition",
      active === k
        ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
        : "text-zinc-700 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800",
    ].join(" ");

  return (
    <header className="sticky top-0 z-20 border-b border-zinc-200/70 bg-white/80 backdrop-blur dark:border-zinc-800/70 dark:bg-zinc-950/80">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-lg bg-zinc-900 dark:bg-zinc-100" />
          <div>
            <div className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              ai-scripts
            </div>
            <div className="text-xs text-zinc-500 dark:text-zinc-400">
              Local tools UI
            </div>
          </div>
        </div>

        <nav className="flex items-center gap-2">
          <button className={linkClass("voice")} onClick={() => onNav("voice")}>
            Voice
          </button>
          <button className={linkClass("tools")} onClick={() => onNav("tools")}>
            Tools
          </button>
          <button
            className={linkClass("settings")}
            onClick={() => onNav("settings")}
          >
            Settings
          </button>

          <div className="mx-2 h-6 w-px bg-zinc-200 dark:bg-zinc-800" />

          <button
            onClick={() => setTheme(toggleTheme(theme))}
            className="rounded-md px-3 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            {theme === "dark" ? "Light" : "Dark"}
          </button>
        </nav>
      </div>
    </header>
  );
}
