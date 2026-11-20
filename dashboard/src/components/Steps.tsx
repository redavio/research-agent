import type { Results } from "../types";
import { TOOL, ui } from "./ui";

const cell = "border-b border-zinc-200 px-2 py-2 dark:border-zinc-700";

/** Every step the agent chose, from reading sources to saving findings. */
export default function Steps({ res }: { res: Results }) {
  const calls = res.steps_taken.flatMap((s) => s.calls.map((c) => ({ ...c, step: s.step })));
  return (
    <section className="overflow-x-auto" data-shot="3">
      <p className={ui.help}>Every step below was the agent's own choice: which source to read, what to open, what to keep, and when to stop.</p>
      <table className="mb-4 mt-2 w-full border-collapse text-sm">
        <thead>
          <tr>
            {["Step", "What it did", "Result"].map((h) => (
              <th key={h} className={`${cell} text-left font-medium ${ui.muted}`}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {calls.map((c, i) => (
            <tr key={i}>
              <td className={`${cell} whitespace-nowrap ${ui.muted}`}>{c.step}</td>
              <td className={cell}>{TOOL[c.tool] ?? c.tool} {c.arg && <span className={ui.muted}>{c.arg}</span>}</td>
              <td className={`${cell} whitespace-nowrap ${c.ok ? "text-brand" : ui.bad}`}>
                {c.ok ? "✓" : c.tool.startsWith("fetch") ? "✕ couldn't read, moved on" : "✕ rejected"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
