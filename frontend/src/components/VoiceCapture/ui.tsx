export function Card(props: {
  title: string;
  children: React.ReactNode;
  right?: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
          {props.title}
        </h2>
        {props.right}
      </div>
      {props.children}
    </div>
  );
}

export function Label(props: { children: React.ReactNode }) {
  return (
    <div className="text-xs text-zinc-500 dark:text-zinc-400">
      {props.children}
    </div>
  );
}

export function PreBox(props: { children: React.ReactNode }) {
  return (
    <pre className="whitespace-pre-wrap break-words rounded-lg bg-zinc-50 p-3 text-sm text-zinc-900 dark:bg-zinc-900/40 dark:text-zinc-100">
      {props.children}
    </pre>
  );
}

export function Tooltip(props: { text: string }) {
  return (
    <span className="group relative inline-flex items-center">
      <span className="ml-2 inline-flex h-5 w-5 items-center justify-center rounded-full border border-zinc-300 text-[11px] text-zinc-600 dark:border-zinc-700 dark:text-zinc-300">
        i
      </span>
      <span className="pointer-events-none absolute left-0 top-7 z-20 hidden w-80 whitespace-pre-wrap rounded-lg border border-zinc-200 bg-white p-3 text-xs text-zinc-700 shadow-lg group-hover:block dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-200">
        {props.text}
      </span>
    </span>
  );
}
