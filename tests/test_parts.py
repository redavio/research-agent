"""Guardrail, config, memory dedup, and save_finding checks."""

from pathlib import Path

import pytest
from conftest import BASE_CONFIG, make_toolbox

from research_agent.config import ConfigError, load_config, parse_config
from research_agent.guardrail import check_numbers, numbers_in
from research_agent.memory import Memory

ROOT = Path(__file__).resolve().parents[1]


# ---- number guardrail -------------------------------------------------------------------
def test_numbers_found_in_tool_results_pass():
    res = check_numbers("Price rose to $1,299 (12.5%) on Nov 5.",
                        ['{"text": "now 1299 dollars, a 12.50% jump, 2026-11-05"}'])
    assert res["unverified"] == [] and res["checked"] == 3


def test_invented_numbers_are_flagged():
    res = check_numbers("Revenue grew 40% to $3M.", ['{"text": "revenue grew"}'])
    assert res["unverified"] == ["40%", "$3"]


def test_urls_and_list_markers_are_not_counted():
    assert numbers_in("1. See [post](https://x.com/a/2024/99) and https://y.com/123\n2. ok") == []


# ---- config -----------------------------------------------------------------------------
def test_example_config_loads():
    cfg = load_config(ROOT / "config.example.yaml", env={})
    assert cfg.provider == "openai" and cfg.model == "gpt-4.1-mini"
    assert any(s["type"] == "web" and s["id"].startswith("competitor-") for s in cfg.sources)
    assert cfg.max_steps == 40 and cfg.max_cost_usd == 0.40


def test_env_overrides_provider_and_model(tmp_path):
    cfg = parse_config(dict(BASE_CONFIG), tmp_path, env={"RESEARCH_LLM_PROVIDER": "anthropic"})
    assert cfg.provider == "anthropic" and cfg.model.startswith("claude-")
    cfg = parse_config(dict(BASE_CONFIG), tmp_path, env={"RESEARCH_LLM_MODEL": "gpt-4.1"})
    assert cfg.model == "gpt-4.1"


@pytest.mark.parametrize("bad", [
    {**BASE_CONFIG, "business": {"to": "x"}},
    {**BASE_CONFIG, "sources": [{"type": "fax", "url": "x"}]},
    {**BASE_CONFIG, "sources": [{"type": "hackernews"}]},
])
def test_bad_config_is_rejected(bad, tmp_path):
    with pytest.raises(ConfigError):
        parse_config(bad, tmp_path, env={})


# ---- memory -----------------------------------------------------------------------------
def test_repeat_sighting_bumps_counter_instead_of_duplicating():
    m = Memory(":memory:")
    a = m.save_finding("r1", "Acme raises prices", "why", ["https://www.news.example.com/a?utm=1"], "q")
    b = m.save_finding("r2", "Different headline, same story", "why", ["http://news.example.com/a/"], "q")
    c = m.save_finding("r3", "ACME raises prices!", "why", ["https://other.example.com/b"], "q")
    assert a["status"] == "new" and b["status"] == "seen_before" and c["status"] == "seen_before"
    assert c["sightings"] == 3
    assert len(m.recall()) == 1


def test_same_run_save_does_not_bump():
    m = Memory(":memory:")
    m.save_finding("r1", "X", "why", ["https://a.example.com"], "q")
    again = m.save_finding("r1", "X", "why", ["https://a.example.com"], "q")
    assert again["status"] == "already_saved_this_run" and again["sightings"] == 1


def test_page_change_detection():
    m = Memory(":memory:")
    assert m.page_changed("https://a.example.com/p", "v1") == "first_time"
    assert m.page_changed("https://a.example.com/p", "v1") == "unchanged"
    assert m.page_changed("https://a.example.com/p", "v2") == "changed"


# ---- save_finding evidence checks -------------------------------------------------------
def test_save_finding_rejects_unfetched_url_and_fake_quote(cfg, memory):
    tb = make_toolbox(cfg, memory)
    tb.call("fetch_source", {"source_id": "news"})
    out, ok = tb.call("save_finding", {"title": "t", "why_it_matters": "w", "source_urls": ["https://never.example.com"],
                                       "evidence_quote": "something long enough here"})
    assert not ok and "not fetched" in out
    out, ok = tb.call("save_finding", {"title": "t", "why_it_matters": "w", "source_urls": ["https://news.example.com/acme-prices"],
                                       "evidence_quote": "prices fell by half across the board"})
    assert not ok and "word for word" in out
    out, ok = tb.call("save_finding", {"title": "t", "why_it_matters": "w", "source_urls": ["https://news.example.com/acme-prices"],
                                       "evidence_quote": "Pro plan now costs $59 per user"})
    assert ok and '"new"' in out


def test_items_already_reported_are_marked(cfg, memory):
    memory.save_finding("old", "Acme price", "w", ["https://news.example.com/acme-prices"], "q")
    tb = make_toolbox(cfg, memory, "new")
    out, _ = tb.call("fetch_source", {"source_id": "news"})
    assert '"already_reported_in_a_past_run": true' in out
