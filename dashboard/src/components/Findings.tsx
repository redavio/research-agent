import type { Results } from "../types";
import { date, ui } from "./ui";

/** Each finding, why it matters, and the source it came from. */
export default function Findings({ res }: { res: Results }) {
  return (
    <section className="overflow-x-auto" data-shot="2">
      <p className={ui.help}>
        What the agent saved this run, each backed by a word-for-word quote from a page it fetched. A story it reported before is not saved twice: its sighting count goes up instead.
      </p>
      {res.findings.length === 0 && <p className={ui.note}>No findings saved this run.</p>}
      <div className="grid gap-3">
        {res.findings.map((f) => (
          <article key={f.finding_id} className={ui.card}>
            <div className="flex items-start justify-between gap-3">
              <h3 className="font-semibold">{f.title}</h3>
              <span
                className={`${ui.tag} ${f.status === "new" ? "border-brand text-brand" : `border-zinc-200 dark:border-zinc-700 ${ui.muted}`}`}
                title={`First seen ${date(f.first_seen_at)}`}
              >
                {f.status === "new" ? "new" : `seen ${f.sightings} times`}
              </span>
            </div>
            <p className="my-2 text-sm leading-relaxed">{f.why_it_matters}</p>
            <div className="text-xs">
              {f.source_urls.map((u) => (
                <a key={u} href={u} target="_blank" rel="noopener" className={`mr-3 inline-block ${ui.link}`}>
                  {u.replace(/^https?:\/\/(www\.)?/, "")}
                </a>
              ))}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
