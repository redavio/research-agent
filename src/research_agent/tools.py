"""The tools the model can call.

Every tool is read-only toward the outside world. The only write is `save_finding`, which
writes to the local SQLite memory file. There is no tool that posts, emails, or changes
anything anywhere else; that is the "human approves changes" rule, enforced by absence.

Every tool returns a JSON string. A failure returns {"error": "..."} so the model can read
it and decide what to do next, instead of the run crashing.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Callable

from .config import Config
from .http import FetchError, html_to_text
from . import http
from .memory import Memory, normalize_url
from .sources import FETCHERS, search_hackernews

SNIPPET = 280

TOOL_SPECS: list[dict] = [
    {"name": "list_sources",
     "description": "List the configured sources (id, type, what it covers). Start here if you do not know what is available.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "fetch_source",
     "description": "Fetch one configured source by id. Returns a list of items (id, title, url, date, short snippet). "
                    "Items older than the lookback window are dropped. Web pages report whether they changed since the last run.",
     "parameters": {"type": "object", "properties": {"source_id": {"type": "string"}}, "required": ["source_id"]}},
    {"name": "search_hackernews",
     "description": "Search recent Hacker News stories for a query. Good for spotting what people are talking about.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "fetch_url",
     "description": "Fetch any public web page by URL and return it as a readable item (for following a link you saw).",
     "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
    {"name": "read_item",
     "description": "Read the full text of an item returned by fetch_source, search_hackernews or fetch_url.",
     "parameters": {"type": "object", "properties": {"item_id": {"type": "string"}}, "required": ["item_id"]}},
    {"name": "recall_findings",
     "description": "What earlier runs already reported (with how many times each was seen). Use it to avoid repeating old news.",
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string", "description": "optional word to filter on"},
         "days": {"type": "integer", "description": "how far back, default 90"}}, "required": []}},
    {"name": "save_finding",
     "description": "Save something worth reporting. source_urls must be URLs you fetched this run, and evidence_quote must be "
                    "copied word for word from an item you fetched. If it was reported before, the sighting count goes up instead.",
     "parameters": {"type": "object", "properties": {
         "title": {"type": "string"},
         "why_it_matters": {"type": "string", "description": "why this matters to this business, in one or two sentences"},
         "source_urls": {"type": "array", "items": {"type": "string"}},
         "evidence_quote": {"type": "string", "description": "exact quote from the source"}},
         "required": ["title", "why_it_matters", "source_urls", "evidence_quote"]}},
    {"name": "finish",
     "description": "End the run with a markdown brief for the reader. Only use numbers that appear in what you fetched.",
     "parameters": {"type": "object", "properties": {"brief": {"type": "string"}}, "required": ["brief"]}},
    {"name": "finish_nothing",
     "description": "End the run saying nothing is worth reporting this time, and why. This is a good outcome when true.",
     "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}},
]

TERMINAL_TOOLS = {"finish", "finish_nothing"}


def _norm_text(s: str) -> str:
    s = s.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"[^a-z0-9$%.,' ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


class Toolbox:
    def __init__(self, config: Config, memory: Memory, run_id: str,
                 fetchers: dict[str, Callable] | None = None,
                 hn_search: Callable | None = None,
                 url_fetcher: Callable | None = None,
                 now: datetime | None = None) -> None:
        self.cfg = config
        self.memory = memory
        self.run_id = run_id
        self.fetchers = fetchers or FETCHERS
        self.hn_search = hn_search or search_hackernews
        self.url_fetcher = url_fetcher or _fetch_url
        self.now = now or datetime.now(timezone.utc)
        self.items: dict[str, dict] = {}
        self.result_log: list[str] = []      # every tool result text, for the number guardrail
        self.saved: list[dict] = []
        self.finished: dict | None = None    # {"kind": "brief"|"nothing", "text": ...}
        self._failed_calls: set[str] = set()
        self._handlers = {
            "list_sources": self.list_sources, "fetch_source": self.fetch_source,
            "search_hackernews": self.search_hackernews, "fetch_url": self.fetch_url,
            "read_item": self.read_item, "recall_findings": self.recall_findings,
            "save_finding": self.save_finding, "finish": self.finish, "finish_nothing": self.finish_nothing,
        }

    @property
    def specs(self) -> list[dict]:
        return TOOL_SPECS

    def call(self, name: str, args: dict) -> tuple[str, bool]:
        """Run one tool. Returns (result_json, ok). Never raises."""
        handler = self._handlers.get(name)
        key = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
        if key in self._failed_calls:
            out, ok = {"error": f"this exact {name} call already failed this run. Do something different, "
                                "or move on."}, False
        elif handler is None:
            out, ok = {"error": f"unknown tool '{name}'. Available: {sorted(self._handlers)}"}, False
        elif not isinstance(args, dict):
            out, ok = {"error": f"arguments for {name} were not valid JSON"}, False
        else:
            try:
                out = handler(**args)
                ok = "error" not in out
            except TypeError as e:
                out, ok = {"error": f"bad arguments for {name}: {e}"}, False
            except FetchError as e:
                out, ok = {"error": str(e)}, False
            except Exception as e:  # noqa: BLE001 - any tool failure goes back to the model
                out, ok = {"error": f"{type(e).__name__}: {e}"}, False
        if not ok:
            self._failed_calls.add(key)
        text = json.dumps(out, ensure_ascii=False, default=str)
        if len(text) > self.cfg.max_result_chars:
            text = text[: self.cfg.max_result_chars] + '... [truncated; use read_item for full text]"'
        self.result_log.append(text)
        return text, ok

    # ---- tools -------------------------------------------------------------------------
    def list_sources(self) -> dict:
        return {"sources": [
            {"id": s["id"], "type": s["type"], "url": s.get("url"), "query": s.get("query"), "note": s.get("note")}
            for s in self.cfg.sources]}

    def _register(self, prefix: str, items: list[dict]) -> list[dict]:
        cutoff = self.now - timedelta(days=self.cfg.lookback_days)
        listed, dropped = [], 0
        for it in items:
            pub = it.get("published")
            if pub:
                try:
                    if datetime.fromisoformat(pub) < cutoff:
                        dropped += 1
                        continue
                except ValueError:
                    pass
            iid = f"{prefix}:{len(self.items) + 1}"
            self.items[iid] = it
            listed.append({
                "item_id": iid, "title": it.get("title"), "url": it.get("url"), "published": pub,
                "snippet": (it.get("text") or "")[:SNIPPET],
                "already_reported_in_a_past_run": self.memory.is_reported(it.get("url") or ""),
            })
        self._dropped_old = dropped
        return listed

    def fetch_source(self, source_id: str) -> dict:
        src = next((s for s in self.cfg.sources if s["id"] == source_id), None)
        if src is None:
            return {"error": f"no source with id '{source_id}'. Call list_sources to see ids."}
        items = self.fetchers[src["type"]](src)
        out: dict = {"source_id": source_id, "type": src["type"]}
        if src["type"] == "web" and items:
            out["page_status_since_last_run"] = self.memory.page_changed(items[0]["url"], items[0].get("text") or "")
        out["items"] = self._register(source_id, items)
        out["older_items_dropped"] = self._dropped_old
        if not out["items"]:
            out["note"] = f"No items in the last {self.cfg.lookback_days} days."
        return out

    def search_hackernews(self, query: str) -> dict:
        items = self._register("hn", self.hn_search(query))
        return {"query": query, "items": items, "older_items_dropped": self._dropped_old}

    def fetch_url(self, url: str) -> dict:
        if not re.match(r"^https?://", url):
            return {"error": "url must start with http:// or https://"}
        items = self.url_fetcher(url)
        for it in items:
            it.setdefault("aliases", []).append(url)
        listed = self._register("url", items)
        return {"items": listed}

    def read_item(self, item_id: str) -> dict:
        it = self.items.get(item_id)
        if it is None:
            return {"error": f"no item '{item_id}' this run. Item ids come from fetch_source, search_hackernews or fetch_url."}
        return {"item_id": item_id, "title": it.get("title"), "url": it.get("url"),
                "published": it.get("published"), "text": it.get("text")}

    def recall_findings(self, query: str | None = None, days: int = 90) -> dict:
        found = self.memory.recall(days=int(days), query=query)
        return {"findings": found, "count": len(found)}

    def save_finding(self, title: str, why_it_matters: str, source_urls: list, evidence_quote: str) -> dict:
        if isinstance(source_urls, str):
            source_urls = [source_urls]
        if not source_urls:
            return {"error": "source_urls is empty; cite at least one URL you fetched"}
        known = {}
        for it in self.items.values():
            for u in [it.get("url") or ""] + list(it.get("aliases") or []):
                known[normalize_url(u)] = it
        unseen = [u for u in source_urls if normalize_url(u) not in known]
        if unseen:
            return {"error": f"these URLs were not fetched this run: {unseen}. Fetch them first or cite a URL you did fetch."}
        quote = _norm_text(evidence_quote)
        if len(quote) < 12:
            return {"error": "evidence_quote is too short; copy a full sentence or phrase from the source"}
        texts = [_norm_text((it.get("title") or "") + " " + (it.get("text") or "")) for it in self.items.values()]
        if not any(quote[:200] in t for t in texts):
            return {"error": "evidence_quote was not found word for word in any fetched item. Copy one short "
                             "sentence (under 30 words) exactly as it appears in read_item, with no added words."}
        res = self.memory.save_finding(self.run_id, title, why_it_matters, list(source_urls), evidence_quote)
        if res["status"] == "new":
            self.saved.append(res)
            res["note"] = "Saved."
        elif res["status"] == "seen_before":
            self.saved.append(res)
            res["note"] = (f"Already reported in an earlier run (first seen {res['first_seen_at']}). "
                           f"Sighting count is now {res['sightings']}. Only report it again if something new happened.")
        else:
            res["note"] = "Already saved this run; nothing changed."
        return res

    def finish(self, brief: str) -> dict:
        if not brief or not brief.strip():
            return {"error": "brief is empty. Write the brief, or call finish_nothing."}
        self.finished = {"kind": "brief", "text": brief.strip()}
        return {"ok": True}

    def finish_nothing(self, reason: str) -> dict:
        if not reason or not reason.strip():
            return {"error": "give a short reason"}
        self.finished = {"kind": "nothing", "text": reason.strip()}
        return {"ok": True}


def _fetch_url(url: str) -> list[dict]:
    resp = http.get(url)
    ctype = resp.headers.get("content-type", "")
    if "html" not in ctype and "text" not in ctype and "xml" not in ctype and "json" not in ctype:
        raise FetchError(f"{url} is not a text page (content-type {ctype})")
    title, text = html_to_text(resp.text)
    if not text:
        raise FetchError(f"{url} returned no readable text")
    return [{"title": title or url, "url": str(resp.url), "published": None, "text": text[:20000]}]
