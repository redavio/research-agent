"""An app can supply its own system prompt (e.g. from its database); the built-in one is the default."""
from research_agent.agent import SYSTEM_PROMPT, build_system_prompt
from research_agent.config import parse_config

BASE = {"business": {"name": "Acme", "sells": "widgets", "to": "teams"}, "sources": [{"type": "rss", "url": "https://a.example/f"}]}


def test_default_prompt_is_built_in():
    cfg = parse_config(BASE, env={})
    assert cfg.system_prompt is None
    assert build_system_prompt(cfg, "2026-11-20").startswith(SYSTEM_PROMPT[:40])


def test_supplied_prompt_is_used_with_the_same_fields():
    cfg = parse_config({**BASE, "llm": {"system_prompt": "Work for {name}, who sells {sells}. Today is {today}."}}, env={})
    assert build_system_prompt(cfg, "2026-11-20") == "Work for Acme, who sells widgets. Today is 2026-11-20."
