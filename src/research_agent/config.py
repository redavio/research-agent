"""Load and validate config.yaml. Plain dicts in, one Config object out."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SOURCE_TYPES = {"rss", "web", "youtube", "reddit"}
DEFAULT_GOAL = "Find what changed in my market this week that matters to me."


class ConfigError(ValueError):
    pass


@dataclass
class Config:
    goal: str
    business: dict
    competitors: list[dict]
    sources: list[dict]
    care_about: list[str]
    ignore: list[str]
    lookback_days: int = 7
    max_steps: int = 40
    max_cost_usd: float = 0.40
    max_result_chars: int = 6000
    provider: str = "openai"
    model: str = "gpt-4.1-mini"
    temperature: float = 0.2
    price_per_mtok: dict | None = None
    output_dir: Path = Path("runs")
    memory_path: Path = Path("research_memory.sqlite")
    # Optional: the app's own system prompt (same {placeholders} as agent.SYSTEM_PROMPT). None = built in.
    system_prompt: str | None = None
    raw: dict = field(default_factory=dict)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"


def load_config(path: str | Path, env: dict | None = None) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    data = yaml.safe_load(path.read_text()) or {}
    return parse_config(data, base_dir=path.parent, env=env)


def parse_config(data: dict, base_dir: Path = Path("."), env: dict | None = None) -> Config:
    env = os.environ if env is None else env
    if not isinstance(data, dict):
        raise ConfigError("config must be a mapping")

    business = data.get("business") or {}
    if not business.get("sells"):
        raise ConfigError("business.sells is required (what you sell)")
    if not business.get("to"):
        raise ConfigError("business.to is required (who you sell to)")

    competitors = data.get("competitors") or []
    sources: list[dict] = []
    seen_ids: set[str] = set()

    def add(src: dict) -> None:
        if src.get("type") not in SOURCE_TYPES:
            raise ConfigError(f"source {src} has unknown type; use one of {sorted(SOURCE_TYPES)}")
        if not src.get("url"):
            raise ConfigError(f"{src['type']} source needs a url: {src}")
        sid = src.get("id") or f"{src['type']}-{len(sources) + 1}"
        if sid in seen_ids:
            raise ConfigError(f"duplicate source id: {sid}")
        seen_ids.add(sid)
        sources.append({**src, "id": sid})

    for src in data.get("sources") or []:
        add(dict(src))
    for comp in competitors:
        if not comp.get("name"):
            raise ConfigError(f"competitor needs a name: {comp}")
        for i, url in enumerate(comp.get("urls") or [], start=1):
            add({"id": f"competitor-{_slug(comp['name'])}-{i}", "type": "web", "url": url,
                 "note": f"Competitor: {comp['name']}", "competitor": comp["name"]})

    if not sources:
        raise ConfigError("at least one source or competitor url is required")

    limits = data.get("limits") or {}
    llm = data.get("llm") or {}
    output = data.get("output") or {}
    provider = (env.get("RESEARCH_LLM_PROVIDER") or llm.get("provider") or "openai").lower()
    if provider not in {"openai", "anthropic"}:
        raise ConfigError(f"llm provider must be openai or anthropic, got {provider}")
    default_model = "gpt-4.1-mini" if provider == "openai" else "claude-haiku-4-5"
    model = env.get("RESEARCH_LLM_MODEL") or (llm.get("model") if llm.get("provider", provider) == provider else None) or default_model

    out_dir = Path(output.get("dir") or "runs")
    mem = Path(output.get("memory_path") or "research_memory.sqlite")
    return Config(
        goal=str(data.get("goal") or DEFAULT_GOAL),
        business=business,
        competitors=competitors,
        sources=sources,
        care_about=list(data.get("care_about") or []),
        ignore=list(data.get("ignore") or []),
        lookback_days=int(data.get("lookback_days") or 7),
        max_steps=int(limits.get("max_steps") or 40),
        max_cost_usd=float(limits.get("max_cost_usd") or 0.40),
        max_result_chars=int(limits.get("max_result_chars") or 6000),
        provider=provider,
        model=model,
        temperature=float(llm.get("temperature", 0.2)),
        price_per_mtok=llm.get("price_per_mtok"),
        output_dir=out_dir if out_dir.is_absolute() else base_dir / out_dir,
        memory_path=mem if mem.is_absolute() else base_dir / mem,
        system_prompt=llm.get("system_prompt") or None,
        raw=data,
    )


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env reader. Existing environment variables always win."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)
