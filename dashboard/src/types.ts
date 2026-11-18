// Shape of results.json, written by the CLI for every run (runs/<run>-results.json, see cli.py).

export interface Call {
  tool: string;
  /** One readable line: the source, the item's headline, or the finding's title. */
  arg: string;
  ok: boolean;
}

export interface Finding {
  status: "new" | "seen_before";
  finding_id: number;
  title: string;
  why_it_matters: string;
  source_urls: string[];
  first_seen_at: string;
  last_seen_at: string;
  sightings: number;
}

export interface Results {
  tool: string;
  version: number;
  run_id: string;
  ran_at: string | null;
  goal: string;
  business: { name: string | null; sells: string | null; to: string | null };
  provider: string;
  model: string;
  kind: "brief" | "nothing" | "capped";
  stop_reason: string;
  steps: number;
  cost_usd: number;
  /** The agent's brief in Markdown, or its reason when there was nothing to report. */
  brief: string;
  number_check: { checked: number; verified: string[]; unverified: string[] };
  failed_sources: string[];
  findings: Finding[];
  steps_taken: { step: number; calls: Call[] }[];
}
