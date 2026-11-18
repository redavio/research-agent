"""Command line: research-agent run --config config.yaml"""

from __future__ import annotations

import argparse
import json
import html
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from .agent import RunResult, failed_sources, run_agent, to_json, tool_order
from .config import Config, ConfigError, load_config, load_dotenv
from .llm import make_provider
from .memory import Memory
from .tools import Toolbox


def render_markdown(result: RunResult, cfg: Config) -> str:
    head = f"# Research brief: {cfg.business.get('name', '')}\n\n_Run {result.run_id} · goal: {cfg.goal}_\n\n"
    if result.kind == "nothing":
        body = f"**Nothing worth reporting this run.**\n\n{result.text}\n"
    else:
        body = result.text + "\n"
    nc = result.number_check
    if result.kind == "brief":
        if nc["unverified"]:
            check = ("\n---\n**Number check: UNVERIFIED.** These numbers in the brief were not found in any source "
                     f"the agent read this run: {', '.join(nc['unverified'])}. Treat them as unconfirmed.\n")
        else:
            check = f"\n---\nNumber check: all {nc['checked']} numbers in the brief were found in sources read this run.\n"
    else:
        check = ""
    fails = failed_sources(result)
    check += ("\n**Sources that failed this run:**\n" + "\n".join(f"- {f}" for f in fails) + "\n") if fails else \
        "\nNo source failed this run.\n"
    foot = (f"\n_Stopped by: {result.stop_reason} · steps: {result.steps} · "
            f"estimated cost: ${result.cost_usd:.4f} ({cfg.provider} {cfg.model})_\n")
    return head + body + check + foot


def call_summary(call: dict) -> str:
    """One readable line for a tool call: the source, finding title, or the headline of the item it read."""
    args = call.get("args") or {}
    if call["tool"] == "read_item":
        found = re.search(r'"title":\s*"((?:[^"\\]|\\.)*)"', call.get("result_preview") or "")
        if not found:
            return str(args.get("item_id", ""))
        # The title comes from JSON in the preview: undo its escapes and any HTML entities in it.
        try:
            title = json.loads(f'"{found.group(1)}"')
        except ValueError:
            title = found.group(1)
        return html.unescape(title)[:120]
    for key in ("source_id", "url", "query", "title"):
        if args.get(key):
            return str(args[key])[:120]
    return ""


def to_results(result: RunResult, cfg: Config) -> dict:
    """The run in the shape the dashboard reads (dashboard/public/results.json)."""
    ran_at = datetime.strptime(result.run_id, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat() \
        if re.fullmatch(r"\d{8}T\d{6}Z", result.run_id) else None
    return {
        "tool": "Research Agent", "version": 1, "run_id": result.run_id, "ran_at": ran_at, "goal": cfg.goal,
        "business": {k: cfg.business.get(k) for k in ("name", "sells", "to")},
        "provider": cfg.provider, "model": cfg.model,
        "kind": result.kind, "stop_reason": result.stop_reason, "steps": result.steps,
        "cost_usd": round(result.cost_usd, 4),
        "brief": result.text,
        "number_check": result.number_check,
        "failed_sources": failed_sources(result),
        "findings": result.saved_findings,
        "steps_taken": [
            {"step": e["step"], "calls": [{"tool": c["tool"], "arg": call_summary(c), "ok": c["ok"]} for c in e["calls"]]}
            for e in result.log if e.get("calls")
        ],
    }


def cmd_run(args: argparse.Namespace) -> int:
    load_dotenv(args.env_file)
    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    if args.goal:
        cfg.goal = args.goal
    if args.max_steps:
        cfg.max_steps = args.max_steps
    if args.max_cost:
        cfg.max_cost_usd = args.max_cost

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    memory = Memory(cfg.memory_path)
    memory.start_run(run_id, cfg.goal)
    toolbox = Toolbox(cfg, memory, run_id)
    provider = make_provider(cfg.provider, cfg.model, cfg.temperature)

    def show(entry: dict) -> None:
        if args.quiet:
            return
        for c in entry["calls"]:
            arg = ", ".join(f"{k}={str(v)[:60]!r}" for k, v in (c["args"] or {}).items() if k not in {"brief"})
            print(f"  step {entry['step']:>2}: {c['tool']}({arg}){'' if c['ok'] else '  -> ERROR'}", file=sys.stderr)

    print(f"research-agent: {cfg.provider} {cfg.model}, max {cfg.max_steps} steps / ${cfg.max_cost_usd}", file=sys.stderr)
    result = run_agent(cfg, provider, toolbox, run_id, on_step=show)
    memory.finish_run(run_id, result.stop_reason, result.steps, result.cost_usd)

    md = render_markdown(result, cfg)
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    brief_path = cfg.output_dir / f"{run_id}-brief.md"
    log_path = cfg.output_dir / f"{run_id}-log.json"
    results_path = cfg.output_dir / f"{run_id}-results.json"
    brief_path.write_text(md)
    log_path.write_text(to_json(result, cfg))
    results_path.write_text(json.dumps(to_results(result, cfg), indent=2, default=str))
    print(md)
    print(f"tool order chosen by the model: {' -> '.join(tool_order(result))}", file=sys.stderr)
    print(f"saved: {brief_path}, {log_path} and {results_path} (open it in the dashboard)", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="research-agent", description="A goal-driven market research agent.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run the agent once")
    run.add_argument("--config", default="config.yaml")
    run.add_argument("--env-file", default=".env", help="optional .env with API keys (env vars win)")
    run.add_argument("--goal", help="override the goal in the config")
    run.add_argument("--max-steps", type=int)
    run.add_argument("--max-cost", type=float, help="max estimated USD for this run")
    run.add_argument("--quiet", action="store_true", help="do not print each step")
    args = parser.parse_args(argv)
    if args.command == "run":
        return cmd_run(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
