# research-agent

A small market research agent. You give it a goal, like *"Find what changed in my market this week that matters to me."* It decides which sources to read, in what order, what is worth reporting, and when it is done. Then it hands you a short brief, or tells you nothing was worth your time.

It only reads and reports. It cannot post, email, buy, or change anything.

## Is it really an agent?

| # | Test | How this repo meets it |
|---|------|------------------------|
| 1 | **Goal, not a script** | The run starts from a goal in `config.yaml` (or `--goal`). There is no list of steps anywhere in the code. |
| 2 | **Tools** | The model calls 8 tools: `list_sources`, `fetch_source`, `fetch_url`, `read_item`, `recall_findings`, `save_finding`, `finish`, `finish_nothing` (`tools.py`). |
| 3 | **It chooses** | Each turn the model picks the next tool. The loop in `agent.py` just runs what it picked. Two runs with the same config can take different paths; each run's log in `runs/` shows the one it took. |
| 4 | **It reacts** | Every tool result goes back into the conversation before the model's next turn. |
| 5 | **It stops itself** | The run ends when the model calls `finish` or `finish_nothing`. Code only enforces a max step count and a max estimated cost. |
| 6 | **It can say "nothing"** | `finish_nothing(reason)` is a normal ending, and the prompt tells it that is a good result when true. |
| 6b | **It handles failure** | A failed tool (403, timeout, missing Reddit credentials, bad arguments, unknown tool) comes back to the model as an error result, never a crash. Repeating an identical failed call is refused. The brief's list of failed sources is written by code from the run log. |
| 7 | **No made-up numbers** | After the run, code pulls every number out of the brief and checks it appears in some tool result. Any that don't are flagged as UNVERIFIED in the output. `save_finding` also rejects URLs that were not fetched and quotes that are not word for word. |
| 8 | **Human approves changes** | No tool writes anywhere except a local SQLite file. You read the brief and decide. |

## Install

```bash
pipx install git+https://github.com/redavio/research-agent
```

Or from a local copy:

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e ".[youtube]"   # [youtube] adds video transcripts; optional
```

## Configure

```bash
cp config.example.yaml config.yaml
```

Edit `config.yaml`: what you sell and to whom, competitors (name and URLs), sources, what you care about, what to ignore, and the caps. Source types: `rss`, `web`, `youtube`, `reddit`. The example is a made-up field service software company.

Put API keys in the environment or a `.env` file next to where you run it (both are git-ignored):

```
OPENAI_API_KEY=...
# or
ANTHROPIC_API_KEY=...
RESEARCH_LLM_PROVIDER=anthropic
RESEARCH_LLM_MODEL=claude-haiku-4-5

# optional, for reddit sources (free "script" app at reddit.com/prefs/apps)
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
```

Default is OpenAI `gpt-4.1-mini`, the cheapest model that handles this well.

## Run

```bash
research-agent run --config config.yaml
research-agent run --config config.yaml --goal "Tell me only if a competitor changed its pricing page."
```

It prints each tool the model chose as it goes, then the brief. Each run saves two files in `runs/`:

- `<run>-brief.md`: the brief, the number check, and the list of sources that failed.
- `<run>-log.json`: every step, every tool call the model chose, token counts and cost.

Memory lives in `research_memory.sqlite`. A story reported before is not saved twice: its sighting count goes up instead, so things that keep coming back stand out. Competitor pages are hashed, so the agent can tell "changed" from "unchanged" from "first time seen".

## Where your data goes

- Your config and what the agent reads go only to the AI provider you choose (OpenAI or Anthropic).
- It reads the public sources you list and any public page it decides to open, and calls Reddit and YouTube if you list those sources.
- Run logs, briefs and memory stay on your machine. Nothing is sent to Redavio.

## Cost

With `gpt-4.1-mini` and the example config, a full run took 15 to 21 steps and cost about $0.04 to $0.07. A narrow goal that ended in "nothing to report" took 4 steps and cost under $0.01. With Anthropic's `claude-haiku-4-5` a full run costs more, about $0.10 to $0.20. The hard cap defaults to $0.40 a run (`limits.max_cost_usd`). Costs are estimates from token counts and the price table in `llm.py`.

## Tests

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

Tests use a scripted fake model and fake sources, so they need no network or keys. They cover model-chosen order, reacting to results, stopping, the nothing path, failures, both caps, the number check, config loading, and memory dedup.

## Limits

- The brief is only as good as the model. `gpt-4.1-mini` sometimes reports things that are only loosely relevant. A stronger model gives sharper judgement for more money.
- The number check proves a number appeared somewhere in what the agent read, not that it is used correctly in context.
- Some sites block bots (the example's third competitor does, on purpose, to show the failure path). Pages that need JavaScript return little text.
- Reddit needs free API credentials. Without them the source returns a clear error and the run carries on.
- YouTube transcripts are best effort; without them the agent sees the video description.
- Pages it reads can contain text written to steer an AI. It can only read and save notes, so the worst case is a misleading brief. Check the sources it cites.
- No web search tool. The agent reads your sources and follows links it finds.

## License

MIT. See `LICENSE`.
