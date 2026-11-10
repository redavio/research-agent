"""The loop: model-chosen order, reacting to results, stopping itself, saying nothing, failures, caps."""

import json

from conftest import ScriptedLLM, call, make_toolbox

from research_agent.agent import run_agent, tool_order
from research_agent.tools import TOOL_SPECS

QUOTE = "the Pro plan now costs $59 per user, up from $49"


def _finish_with_finding(item_id="news:1"):
    return [
        [call("read_item", item_id=item_id)],
        [call("save_finding", title="Acme raised Pro price", why_it_matters="Our price looks cheaper now.",
              source_urls=["https://news.example.com/acme-prices"], evidence_quote=QUOTE)],
        [call("finish", brief="Acme Pro now $59 per user, up from $49. Consider a comparison page.")],
    ]


def test_order_is_chosen_by_the_model_not_the_code(cfg, memory):
    a = ScriptedLLM([[call("list_sources")], [call("fetch_source", source_id="news")], *_finish_with_finding()])
    b = ScriptedLLM([[call("recall_findings")], [call("fetch_source", source_id="competitor-acme-1")],
                     [call("fetch_source", source_id="news")], *_finish_with_finding("news:2")])
    ra = run_agent(cfg, a, make_toolbox(cfg, memory, "ra"), "ra")
    rb = run_agent(cfg, b, make_toolbox(cfg, memory, "rb"), "rb")
    assert tool_order(ra) == ["list_sources", "fetch_source", "read_item", "save_finding", "finish"]
    assert tool_order(rb)[:3] == ["recall_findings", "fetch_source", "fetch_source"]
    assert tool_order(ra) != tool_order(rb)


def test_model_reacts_to_tool_results(cfg, memory):
    """The second turn is decided from the first tool result: it reads whichever item mentions prices."""
    def pick_from_results(history):
        result = json.loads(history[-1]["content"])
        target = next(i["item_id"] for i in result["items"] if "price" in i["title"].lower())
        return [call("read_item", item_id=target)]

    llm = ScriptedLLM([[call("fetch_source", source_id="news")], pick_from_results,
                       [call("finish_nothing", reason="Read it; minor.")]])
    r = run_agent(cfg, llm, make_toolbox(cfg, memory), "r")
    assert r.log[1]["calls"][0]["args"] == {"item_id": "news:1"}
    # the model saw the result of turn 1 before turn 2
    assert llm.seen_histories[1][-1]["role"] == "tool"


def test_model_stops_itself(cfg, memory):
    llm = ScriptedLLM([[call("fetch_source", source_id="news")], *_finish_with_finding(),
                       [call("list_sources")]])  # never reached
    r = run_agent(cfg, llm, make_toolbox(cfg, memory), "r")
    assert r.stop_reason == "model_finished"
    assert r.kind == "brief"
    assert r.steps == 4 < cfg.max_steps
    assert len(llm.turns) == 1  # the extra scripted turn was never requested


def test_model_can_say_nothing(cfg, memory):
    llm = ScriptedLLM([[call("fetch_source", source_id="news")],
                       [call("finish_nothing", reason="Only generic tips this week.")]])
    r = run_agent(cfg, llm, make_toolbox(cfg, memory), "r")
    assert r.kind == "nothing"
    assert r.stop_reason == "model_said_nothing"
    assert "generic tips" in r.text


def test_failed_tool_returns_error_to_model_and_run_continues(cfg, memory):
    llm = ScriptedLLM([[call("fetch_source", source_id="competitor-acme-1")],
                       [call("fetch_source", source_id="reddit")],
                       [call("finish_nothing", reason="Acme pricing page returned 403 and Reddit is not configured.")]])
    r = run_agent(cfg, llm, make_toolbox(cfg, memory, fail={"web"}), "r")
    first = r.log[0]["calls"][0]
    assert first["ok"] is False and "403" in first["result_preview"]
    reddit = r.log[1]["calls"][0]
    assert reddit["ok"] is False and "REDDIT_CLIENT_ID" in reddit["result_preview"]
    # the error text was in the history the model read before deciding its next step
    assert any(m["role"] == "tool" and "403" in m["content"] for m in llm.seen_histories[1])
    assert r.stop_reason == "model_said_nothing"


def test_unknown_tool_and_bad_args_are_errors_not_crashes(cfg, memory):
    llm = ScriptedLLM([[call("send_email", to="x")], [call("read_item")],
                       [call("finish_nothing", reason="done")]])
    r = run_agent(cfg, llm, make_toolbox(cfg, memory), "r")
    assert [c["ok"] for e in r.log for c in e["calls"]] == [False, False, True]


def test_max_steps_cap(cfg, memory):
    cfg.max_steps = 3
    llm = ScriptedLLM([[call("list_sources")]] * 10)
    r = run_agent(cfg, llm, make_toolbox(cfg, memory), "r")
    assert r.stop_reason == "max_steps" and r.kind == "capped" and r.steps == 3


def test_max_cost_cap(cfg, memory):
    cfg.max_cost_usd = 0.001  # each fake step costs $0.00056 at gpt-4.1-mini prices
    llm = ScriptedLLM([[call("list_sources")]] * 10)
    r = run_agent(cfg, llm, make_toolbox(cfg, memory), "r")
    assert r.stop_reason == "max_cost" and r.steps == 2 and r.kind == "capped"


def test_model_that_stops_calling_tools_ends_the_run(cfg, memory):
    llm = ScriptedLLM(["thinking...", "still thinking"])
    r = run_agent(cfg, llm, make_toolbox(cfg, memory), "r")
    assert r.stop_reason == "no_tool_call"


def test_brief_with_made_up_number_is_flagged(cfg, memory):
    llm = ScriptedLLM([[call("fetch_source", source_id="news")],
                       [call("finish", brief="Acme Pro is $59, up from $49, and churn is 37%.")]])
    r = run_agent(cfg, llm, make_toolbox(cfg, memory), "r")
    assert r.number_check["unverified"] == ["37%"]
    assert "59" in "".join(r.number_check["verified"])


def test_no_tool_can_act_on_the_outside_world():
    names = {t["name"] for t in TOOL_SPECS}
    assert names == {"list_sources", "fetch_source", "search_hackernews", "fetch_url", "read_item",
                     "recall_findings", "save_finding", "finish", "finish_nothing"}


def test_repeating_a_failed_call_is_refused_and_failures_are_listed_by_code(cfg, memory):
    from research_agent.agent import failed_sources
    llm = ScriptedLLM([[call("fetch_source", source_id="news")], [call("fetch_source", source_id="news")],
                       [call("finish_nothing", reason="news feed down")]])
    r = run_agent(cfg, llm, make_toolbox(cfg, memory, fail={"rss"}), "r")
    assert "already failed" in r.log[1]["calls"][0]["result_preview"]
    assert failed_sources(r)[0].startswith("fetch_source news: HTTP 503")


def test_llm_api_error_ends_run_cleanly(cfg, memory):
    class Broken:
        def complete(self, *a):
            raise RuntimeError("rate limited")
    r = run_agent(cfg, Broken(), make_toolbox(cfg, memory), "r")
    assert r.stop_reason == "llm_error" and r.kind == "capped" and "rate limited" in r.log[0]["llm_error"]
