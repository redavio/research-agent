import { useEffect, useState } from "react";
import { BRAND } from "./brand";
import type { Results } from "./types";

const TOOL: Record<string, string> = {
  list_sources: "Listed your sources",
  fetch_source: "Read source",
  fetch_url: "Opened a page",
  read_item: "Read an item in full",
  recall_findings: "Checked what it already found",
  save_finding: "Saved a finding:",
  finish: "Wrote the brief",
  finish_nothing: "Decided nothing was worth reporting",
};
const STOPPED: Record<string, string> = {
  model_finished: "it had enough to report",
  model_said_nothing: "nothing met the bar",
  max_steps: "it hit the step limit",
  max_cost: "it hit the cost limit",
  no_tool_call: "the model stopped choosing tools",
  llm_error: "the AI provider returned an error",
};

const TABS = { brief: "Brief", findings: "Findings", steps: "Steps" } as const;
type Tab = keyof typeof TABS;

const date = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "–";

export default function App() {
  const [res, setRes] = useState<Results | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>(() => {
    const v = new URLSearchParams(location.search).get("view");
    return v && v in TABS ? (v as Tab) : "brief";
  });

  useEffect(() => {
    const src = new URLSearchParams(location.search).get("src") || "results.json";
    fetch(src)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`Couldn't load ${src}.`))))
      .then(setRes)
      .catch((e) => setError(e.message));
  }, []);

  const open = (file: File) =>
    file.text().then((t) => {
      try {
        setRes(JSON.parse(t));
        setError("");
      } catch {
        setError("That file isn't a Research Agent results file.");
      }
    });

  return (
    <div className="page">
      <header>
        <div>
          <h1>{BRAND.logo && <img src={BRAND.logo} alt="" className="logo" />}{BRAND.name} <span className="muted">· Run</span></h1>
          {res && (
            <p className="muted">
              {res.business.name ? `${res.business.name}. ` : ""}Ran {date(res.ran_at)}. Goal: {res.goal}
            </p>
          )}
        </div>
        <label className="file">
          Open results file
          <input type="file" accept=".json" onChange={(e) => e.target.files?.[0] && open(e.target.files[0])} />
        </label>
      </header>
      {error && <p className="note">{error} Run the agent, then open runs/&lt;run&gt;-results.json here.</p>}
      {res && (
        <>
          <Headline res={res} />
          <nav>
            {(Object.keys(TABS) as Tab[]).map((t) => (
              <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
                {TABS[t]}
              </button>
            ))}
          </nav>
          {tab === "brief" && <BriefView res={res} />}
          {tab === "findings" && <Findings res={res} />}
          {tab === "steps" && <Steps res={res} />}
        </>
      )}
    </div>
  );
}

function Headline({ res }: { res: Results }) {
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
    <section className="cards">
      {cards.map(([label, value, sub]) => (
        <div key={label} className="card">
          <div className="muted small">{label}</div>
          <div className="big">{value}</div>
          <div className="muted small">{sub}</div>
        </div>
      ))}
    </section>
  );
}

/** Text with bare URLs turned into links, Markdown bold and italics markers removed. */
function Linked({ text }: { text: string }) {
  return (
    <>
      {text.split(/(https?:\/\/[^\s),]+)/g).map((part, i) =>
        /^https?:\/\//.test(part) ? (
          <a key={i} href={part} target="_blank" rel="noopener">{part}</a>
        ) : (
          part.replace(/\*\*/g, "").replace(/^_(.*)_$/, "$1")
        ),
      )}
    </>
  );
}

function BriefView({ res }: { res: Results }) {
  const nc = res.number_check;
  const lines = res.brief.split("\n").filter((l) => l.trim() && !l.startsWith("# ") && l.trim() !== "---");
  return (
    <section className="panel" data-shot="1">
      <h2>{res.kind === "nothing" ? "Nothing worth reporting this run" : res.kind === "capped" ? "Stopped before a brief" : "The brief"}</h2>
      <div className="brief">
        {lines.map((l, i) =>
          /^\s*[-*] /.test(l) ? (
            <p key={i} className="indent"><Linked text={l.replace(/^\s*[-*] /, "")} /></p>
          ) : /^\d+\. /.test(l) ? (
            <p key={i} className="item"><span className="n">{l.match(/^\d+/)![0]}</span><span><Linked text={l.replace(/^\d+\. /, "")} /></span></p>
          ) : (
            <p key={i}><Linked text={l} /></p>
          ),
        )}
      </div>
      {res.kind === "brief" && (
        <p className={nc.unverified.length ? "note warn" : "note"}>
          {nc.unverified.length
            ? `Number check: ${nc.unverified.join(", ")} were not found in any source the agent read. Treat them as unconfirmed.`
            : `Number check: all ${nc.checked} numbers in the brief were found in sources read this run.`}
        </p>
      )}
      {res.failed_sources.length > 0 && (
        <>
          <h3>Sources that failed this run</h3>
          <ul className="fails">{res.failed_sources.map((f) => <li key={f}>{f}</li>)}</ul>
        </>
      )}
      <p className="help foot">
        {res.steps} steps · cost ${res.cost_usd.toFixed(3)} · stopped because {STOPPED[res.stop_reason] ?? res.stop_reason.replace(/_/g, " ")}
      </p>
    </section>
  );
}

function Findings({ res }: { res: Results }) {
  return (
    <section data-shot="2">
      <p className="help">
        What the agent saved this run, each backed by a word-for-word quote from a page it fetched. A story it reported before is not saved twice: its sighting count goes up instead.
      </p>
      {res.findings.length === 0 && <p className="note">No findings saved this run.</p>}
      <div className="findings">
        {res.findings.map((f) => (
          <article key={f.finding_id} className="card finding">
            <div className="row">
              <h3>{f.title}</h3>
              <span className={f.status === "new" ? "tag new" : "tag"} title={`First seen ${date(f.first_seen_at)}`}>
                {f.status === "new" ? "new" : `seen ${f.sightings} times`}
              </span>
            </div>
            <p>{f.why_it_matters}</p>
            <div className="small muted">
              {f.source_urls.map((u) => (
                <a key={u} href={u} target="_blank" rel="noopener" className="src">{u.replace(/^https?:\/\/(www\.)?/, "")}</a>
              ))}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function Steps({ res }: { res: Results }) {
  const calls = res.steps_taken.flatMap((s) => s.calls.map((c) => ({ ...c, step: s.step })));
  return (
    <section data-shot="3">
      <p className="help">Every step below was the agent's own choice: which source to read, what to open, what to keep, and when to stop.</p>
      <table>
        <thead>
          <tr><th>Step</th><th>What it did</th><th>Result</th></tr>
        </thead>
        <tbody>
          {calls.map((c, i) => (
            <tr key={i}>
              <td className="muted">{c.step}</td>
              <td className="wrap">{TOOL[c.tool] ?? c.tool} {c.arg && <span className="muted">{c.arg}</span>}</td>
              <td className={c.ok ? "ok" : "bad"}>{c.ok ? "✓" : c.tool.startsWith("fetch") ? "✕ couldn't read, moved on" : "✕ rejected"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
