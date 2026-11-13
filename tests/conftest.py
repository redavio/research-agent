"""Shared test helpers. No network: every fetcher and the LLM are fakes."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from research_agent.config import parse_config
from research_agent.http import FetchError
from research_agent.llm import LLMResponse, ToolCall
from research_agent.memory import Memory
from research_agent.tools import Toolbox

_ids = itertools.count(1)


def call(name: str, **args) -> ToolCall:
    return ToolCall(id=f"c{next(_ids)}", name=name, args=args)


class ScriptedLLM:
    """Plays back a list of turns. A turn is a list of ToolCalls, a str (plain text), or a
    function(history) -> list[ToolCall] that decides based on what the tools returned."""

    def __init__(self, turns, tokens=(1000, 100)):
        self.turns = list(turns)
        self.tokens = tokens
        self.seen_histories: list[list[dict]] = []

    def complete(self, system, messages, tools):
        self.seen_histories.append([dict(m) for m in messages])
        if not self.turns:
            return LLMResponse("I have nothing else to do.", [], *self.tokens)
        turn = self.turns.pop(0)
        if callable(turn):
            turn = turn(messages)
        if isinstance(turn, str):
            return LLMResponse(turn, [], *self.tokens)
        return LLMResponse(None, list(turn), *self.tokens)


FEED_ITEMS = [
    {"title": "Acme Dispatch raises prices 20% for Pro plan", "url": "https://news.example.com/acme-prices",
     "published": None, "text": "Acme Dispatch said the Pro plan now costs $59 per user, up from $49, starting next month."},
    {"title": "Ten tips for a cooler summer", "url": "https://news.example.com/tips",
     "published": None, "text": "Change your filter often."},
]

PRICING_PAGE = [{"title": "Acme pricing", "url": "https://acme.example.com/pricing", "aliases": ["https://acme.example.com/pricing"],
                 "published": None, "text": "Starter $29. Pro $59 per user per month."}]


def fake_fetchers(fail: set[str] | None = None):
    fail = fail or set()

    def rss(src):
        if "rss" in fail:
            raise FetchError("HTTP 503 from https://news.example.com/feed")
        return [dict(i) for i in FEED_ITEMS]

    def web(src):
        if "web" in fail:
            raise FetchError("HTTP 403 from https://acme.example.com/pricing")
        return [dict(i) for i in PRICING_PAGE]

    def empty(src):
        return []

    from research_agent.sources import fetch_reddit
    return {"rss": rss, "web": web, "youtube": empty, "reddit": fetch_reddit}


BASE_CONFIG = {
    "goal": "Find what changed in my market this week that matters to me.",
    "business": {"name": "Example Co", "sells": "scheduling software", "to": "contractors"},
    "competitors": [{"name": "Acme", "urls": ["https://acme.example.com/pricing"]}],
    "sources": [
        {"id": "news", "type": "rss", "url": "https://news.example.com/feed"},
        {"id": "reddit", "type": "reddit", "url": "https://www.reddit.com/r/example"},
    ],
    "limits": {"max_steps": 12, "max_cost_usd": 1.0},
}


@pytest.fixture(autouse=True)
def no_reddit_creds(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)


@pytest.fixture
def cfg(tmp_path: Path):
    return parse_config(dict(BASE_CONFIG), base_dir=tmp_path, env={})


@pytest.fixture
def memory():
    return Memory(":memory:")


def make_toolbox(cfg, memory, run_id="run1", fail=None):
    return Toolbox(cfg, memory, run_id, fetchers=fake_fetchers(fail),
                   url_fetcher=lambda u: [{"title": u, "url": u, "published": None, "text": "page"}])
