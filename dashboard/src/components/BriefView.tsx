import type { Results } from "../types";
import Linked from "./Linked";
import { STOPPED, ui } from "./ui";

/** The brief: what changed this week and why it matters. */
export default function BriefView({ res }: { res: Results }) {
  const nc = res.number_check;
  const lines = res.brief.split("\n").filter((l) => l.trim() && !l.startsWith("# ") && l.trim() !== "---");
  return (
    <section className="my-2 overflow-x-auto rounded-xl border border-zinc-200 p-5 dark:border-zinc-700" data-shot="1">
      <h2 className="mb-3 text-lg font-semibold">
        {res.kind === "nothing" ? "Nothing worth reporting this run" : res.kind === "capped" ? "Stopped before a brief" : "The brief"}
      </h2>
      <div className="text-sm leading-relaxed">
        {lines.map((l, i) =>
          /^\s*[-*] /.test(l) ? (
            <p key={i} className="mb-3 pl-3.5"><Linked text={l.replace(/^\s*[-*] /, "")} /></p>
          ) : /^\d+\. /.test(l) ? (
            <p key={i} className="mb-3 flex gap-2.5">
              <span className="h-[22px] w-[22px] flex-none rounded-full bg-zinc-100 text-center text-xs font-semibold leading-[22px] dark:bg-zinc-800">
                {l.match(/^\d+/)![0]}
              </span>
              <span><Linked text={l.replace(/^\d+\. /, "")} /></span>
            </p>
          ) : (
            <p key={i} className="mb-3"><Linked text={l} /></p>
          ),
        )}
      </div>
      {res.kind === "brief" && (
        <p className={nc.unverified.length ? ui.warn : ui.note}>
          {nc.unverified.length
            ? `Number check: ${nc.unverified.join(", ")} were not found in any source the agent read. Treat them as unconfirmed.`
            : `Number check: all ${nc.checked} numbers in the brief were found in sources read this run.`}
        </p>
      )}
      {res.failed_sources.length > 0 && (
        <>
          <h3 className="mb-1.5 mt-4 font-semibold">Sources that failed this run</h3>
          <ul className={`list-disc pl-5 text-sm ${ui.bad}`}>{res.failed_sources.map((f) => <li key={f}>{f}</li>)}</ul>
        </>
      )}
      <p className={`${ui.help} mb-0 border-t border-zinc-200 pt-3 dark:border-zinc-700`}>
        {res.steps} steps · cost ${res.cost_usd.toFixed(3)} · stopped because {STOPPED[res.stop_reason] ?? res.stop_reason.replace(/_/g, " ")}
      </p>
    </section>
  );
}
