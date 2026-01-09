import { useState } from "react";
import { Header, type NavKey } from "./components/Header";
import { VoiceCapturePage } from "./components/VoiceCapture";
import { type Theme, getTheme } from "./lib/theme";

function PagePlaceholder(props: { title: string; desc: string }) {
  return (
    <div className="mx-auto max-w-5xl px-4 py-6">
      <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">
        {props.title}
      </h1>
      <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
        {props.desc}
      </p>
    </div>
  );
}

function PageContainer(props: { children: React.ReactNode }) {
  return <main className="mx-auto max-w-5xl px-4 py-6">{props.children}</main>;
}

export default function App() {
  const [active, setActive] = useState<NavKey>("voice");
  const [theme, setTheme] = useState<Theme>(() => getTheme()); // lazy init

  return (
    <div className="min-h-screen bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      <Header
        active={active}
        onNav={setActive}
        theme={theme}
        setTheme={setTheme}
      />

      {active === "voice" && <VoiceCapturePage />}

      {active === "tools" && (
        <PageContainer>
          <PagePlaceholder
            title="Tools"
            desc="Later: list available scripts, run them, show results, and manage history."
          />
        </PageContainer>
      )}

      {active === "settings" && (
        <PageContainer>
          <PagePlaceholder
            title="Settings"
            desc="Later: model selection, threshold defaults, DB retention, and profiles."
          />
        </PageContainer>
      )}
    </div>
  );
}
