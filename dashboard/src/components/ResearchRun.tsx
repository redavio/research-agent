import { useState } from "react";
import type { Results } from "../types";
import BriefView from "./BriefView";
import Findings from "./Findings";
import Headline from "./Headline";
import Steps from "./Steps";
import { date, ui } from "./ui";

export const VIEWS = { brief: "Brief", findings: "Findings", steps: "Steps" } as const;
export type View = keyof typeof VIEWS;

/**
 * The whole Research Agent screen for one run's results.json: a one-line summary, the run's
 * numbers, then Brief / Findings / Steps. Takes the result as props and loads nothing itself,
 * so any app can render it (this repo's dashboard reads a results file; a hosted app can pass
 * the same object from its own API).
 */
export default function ResearchRun({ res, initialView = "brief" }: { res: Results; initialView?: View }) {
  const [view, setView] = useState<View>(initialView);
  return (
    <div>
      <p className={`text-sm ${ui.muted}`}>
        {res.business.name ? `${res.business.name}. ` : ""}Ran {date(res.ran_at)}. Goal: {res.goal}
      </p>
      <Headline res={res} />
      <nav className="mb-2 mt-4 flex flex-wrap gap-1.5">
        {(Object.keys(VIEWS) as View[]).map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => setView(v)}
            className={`rounded-full border px-3.5 py-1.5 text-sm ${
              view === v
                ? "border-brand bg-brand text-white"
                : "border-zinc-200 hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
            }`}
          >
            {VIEWS[v]}
          </button>
        ))}
      </nav>
      {view === "brief" && <BriefView res={res} />}
      {view === "findings" && <Findings res={res} />}
      {view === "steps" && <Steps res={res} />}
    </div>
  );
}
