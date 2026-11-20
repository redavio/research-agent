import type { Results } from "../types";
import { ui } from "./ui";

/** Five numbers about the run: findings, steps, number check, failed sources, cost. */
export default function Headline({ res }: { res: Results }) {
  const nc = res.number_check;
  const fresh = res.findings.filter((f) => f.status === "new").length;
  const cards: [string, string, string][] = [
    ["Findings", String(res.findings.length), `${fresh} new, ${res.findings.length - fresh} seen before`],
    ["Steps", String(res.steps), "each one chosen by the agent"],
    [
      "Number check",
      res.kind !== "brief" ? "–" : nc.unverified.length ? `${nc.unverified.length} unverified` : "All found",
      res.kind !== "brief" ? "no brief to check" : `${nc.checked} numbers checked against sources`,
    ],
    ["Sources failed", String(res.failed_sources.length), res.failed_sources.length ? "listed under the brief" : "every source read"],
    ["Cost", `$${res.cost_usd.toFixed(3)}`, `${res.provider} ${res.model}`],
  ];
  return (
    <section className="my-5 grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-3">
      {cards.map(([label, value, sub]) => (
        <div key={label} className={ui.card}>
          <div className={`text-xs ${ui.muted}`}>{label}</div>
          <div className="my-1 text-2xl font-semibold">{value}</div>
          <div className={`text-xs ${ui.muted}`}>{sub}</div>
        </div>
      ))}
    </section>
  );
}
