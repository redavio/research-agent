// Labels, formatting and shared Tailwind classes for every view.
export const TOOL: Record<string, string> = {
  list_sources: "Listed your sources",
  fetch_source: "Read source",
  fetch_url: "Opened a page",
  read_item: "Read an item in full",
  recall_findings: "Checked what it already found",
  save_finding: "Saved a finding:",
  finish: "Wrote the brief",
  finish_nothing: "Decided nothing was worth reporting",
};
export const STOPPED: Record<string, string> = {
  model_finished: "it had enough to report",
  model_said_nothing: "nothing met the bar",
  max_steps: "it hit the step limit",
  max_cost: "it hit the cost limit",
  no_tool_call: "the model stopped choosing tools",
  llm_error: "the AI provider returned an error",
};

export const date = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "–";

export const ui = {
  muted: "text-zinc-500 dark:text-zinc-400",
  help: "my-3 text-sm text-zinc-500 dark:text-zinc-400",
  card: "rounded-xl border border-zinc-200 p-3.5 dark:border-zinc-700",
  link: "break-all text-brand underline underline-offset-[3px]",
  note: "rounded-lg bg-brand/10 px-3 py-2.5 text-sm",
  warn: "rounded-lg bg-orange-50 px-3 py-2.5 text-sm dark:bg-orange-950/40",
  bad: "text-orange-700 dark:text-orange-400",
  tag: "whitespace-nowrap rounded-full border px-1.5 py-px text-xs",
};
