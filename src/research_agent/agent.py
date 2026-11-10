"""The agent loop.

There is no fixed order of steps in this file. Each turn the model sees everything that has
happened so far (including every tool result), and picks the next tool itself. The loop just
runs what it picked and hands the result back. The model ends the run by calling `finish` or
`finish_nothing`. Code only enforces two hard caps: max steps and max estimated cost.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import Config
from .guardrail import check_numbers
from .llm import price_for
from .tools import TERMINAL_TOOLS, Toolbox

SYSTEM_PROMPT = """You are a market research agent working for one business. You decide what to look at, in what order, and when you are done.

Goal: {goal}

The business:
- Name: {name}
- Sells: {sells}
- To: {to}
- Competitors: {competitors}

Care about: {care}
Ignore: {ignore}
Today is {today}. Only things from the last {lookback} days count as new.

How to work:
- Plan briefly, then use tools. Read each tool result before choosing the next step. Skip sources that look unlikely to help; follow leads that do.
- Before saving something, read the item (read_item) so your judgement is based on the text, not a headline.
- Check recall_findings so you do not report old news as new. If something was already reported, only mention it again if there is a real update, and say how many times it has been seen.
- Save each real finding with save_finding (exact quote, URLs you fetched).
- If a tool returns an error, do not retry the same call more than once. Note what failed and move on.
- You only report. You cannot post, email, buy, or change anything, and you should not suggest you did.
- Most weeks most things do not matter. If nothing meets the bar, call finish_nothing with the reason. That is a good result, not a failure.
- When done, call finish with a short markdown brief: what changed, why it matters to this business, what to consider doing, with source links. End with a line listing any sources that failed.
- Never write a number (price, percent, count, date) unless it appears in a tool result. A code check will flag any number it cannot find in what you read.
"""


@dataclass
class RunResult:
    run_id: str
    kind: str                  # "brief" | "nothing" | "capped"
    text: str
    stop_reason: str           # "model_finished" | "model_said_nothing" | "max_steps" | "max_cost" | "no_tool_call"
    steps: int
    cost_usd: float
    input_tokens: int
    output_tokens: int
    log: list[dict] = field(default_factory=list)
    number_check: dict = field(default_factory=dict)
    saved_findings: list[dict] = field(default_factory=list)


def build_system_prompt(cfg: Config, today: str) -> str:
    b = cfg.business
    return SYSTEM_PROMPT.format(
        goal=cfg.goal, name=b.get("name", "(unnamed)"), sells=b.get("sells"), to=b.get("to"),
        competitors=", ".join(c["name"] for c in cfg.competitors) or "none listed",
        care="; ".join(cfg.care_about) or "anything material", ignore="; ".join(cfg.ignore) or "nothing specific",
        today=today, lookback=cfg.lookback_days)


def run_agent(cfg: Config, provider, toolbox: Toolbox, run_id: str, today: str | None = None,
              on_step=None) -> RunResult:
    today = today or datetime.now(timezone.utc).date().isoformat()
    system = build_system_prompt(cfg, today)
    p_in, p_out = price_for(cfg.model, cfg.price_per_mtok)
    history: list[dict] = [{"role": "user", "content": f"Goal: {cfg.goal}\nStart now."}]
    log: list[dict] = []
    cost = 0.0
    tin = tout = 0
    stop_reason = "max_steps"
    idle_turns = 0
    step = 0

    for step in range(1, cfg.max_steps + 1):
        if cost >= cfg.max_cost_usd:
            stop_reason, step = "max_cost", step - 1
            break
        t0 = time.time()
        resp = provider.complete(system, history, toolbox.specs)
        tin += resp.input_tokens
        tout += resp.output_tokens
        cost += resp.input_tokens / 1e6 * p_in + resp.output_tokens / 1e6 * p_out
        entry = {"step": step, "model_text": resp.text, "calls": [],
                 "input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens,
                 "cost_so_far_usd": round(cost, 5)}
        history.append({"role": "assistant", "content": resp.text, "tool_calls": resp.tool_calls})

        if not resp.tool_calls:
            idle_turns += 1
            log.append(entry)
            if idle_turns >= 2:
                stop_reason = "no_tool_call"
                break
            history.append({"role": "user", "content":
                            "Use a tool. When you are done, call finish or finish_nothing."})
            continue
        idle_turns = 0

        for call in resp.tool_calls:
            if call.args is None:
                result, ok = toolbox.call(call.name, "not-json")  # returns a clean error to the model
            else:
                result, ok = toolbox.call(call.name, call.args)
            remaining = cfg.max_steps - step
            if remaining <= 3 or cost >= 0.8 * cfg.max_cost_usd:
                result += (f"\n[budget note: {remaining} steps and ${max(cfg.max_cost_usd - cost, 0):.3f} left. "
                           "Wrap up soon with finish or finish_nothing.]")
            history.append({"role": "tool", "tool_call_id": call.id, "name": call.name, "content": result})
            entry["calls"].append({"tool": call.name, "args": call.args, "ok": ok,
                                   "result_preview": result[:300], "result_chars": len(result)})
        entry["seconds"] = round(time.time() - t0, 2)
        log.append(entry)
        if on_step:
            on_step(entry)

        if toolbox.finished is not None:
            stop_reason = "model_finished" if toolbox.finished["kind"] == "brief" else "model_said_nothing"
            break
        if any(c.name in TERMINAL_TOOLS for c in resp.tool_calls):
            continue  # finish was called but rejected (e.g. empty brief); the model sees the error

    if toolbox.finished is not None:
        kind, text = toolbox.finished["kind"], toolbox.finished["text"]
    else:
        kind = "capped"
        lines = [f"The run stopped at a hard cap ({stop_reason}) before the agent finished.",
                 "Findings it had saved so far (not reviewed by the agent into a brief):", ""]
        lines += [f"- {f['title']}: {f['why_it_matters']} ({', '.join(f['source_urls'])})" for f in toolbox.saved] or ["- none"]
        text = "\n".join(lines)

    check = check_numbers(text, toolbox.result_log) if kind == "brief" else {"checked": 0, "verified": [], "unverified": []}
    return RunResult(run_id=run_id, kind=kind, text=text, stop_reason=stop_reason, steps=step,
                     cost_usd=round(cost, 5), input_tokens=tin, output_tokens=tout, log=log,
                     number_check=check, saved_findings=toolbox.saved)


def tool_order(result: RunResult) -> list[str]:
    """The sequence of tools the model chose, in order. Handy for proving the order is not fixed."""
    return [c["tool"] for e in result.log for c in e["calls"]]


def to_json(result: RunResult, cfg: Config) -> str:
    return json.dumps({
        "run_id": result.run_id, "goal": cfg.goal, "provider": cfg.provider, "model": cfg.model,
        "kind": result.kind, "stop_reason": result.stop_reason, "steps": result.steps,
        "cost_usd_estimated": result.cost_usd, "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens, "tool_order": tool_order(result),
        "number_check": result.number_check, "saved_findings": result.saved_findings, "steps_detail": result.log,
    }, indent=2, default=str)
