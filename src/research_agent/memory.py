"""Local SQLite memory: what was reported before, and how often it was seen again.

A repeat sighting does not create a second finding. It bumps `sightings` on the first one,
which is the frequency signal: a story that keeps coming back matters more.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
    goal TEXT, stop_reason TEXT, steps INTEGER, cost_usd REAL
);
CREATE TABLE IF NOT EXISTS findings (
    finding_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL, why_it_matters TEXT, evidence_quote TEXT,
    source_urls TEXT NOT NULL,
    first_run_id TEXT, first_seen_at TEXT NOT NULL,
    last_run_id TEXT, last_seen_at TEXT NOT NULL,
    sightings INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS finding_urls (
    url TEXT PRIMARY KEY, finding_id INTEGER NOT NULL REFERENCES findings(finding_id)
);
CREATE TABLE IF NOT EXISTS page_hashes (
    url TEXT PRIMARY KEY, content_hash TEXT NOT NULL, seen_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_url(url: str) -> str:
    url = url.strip().lower()
    url = re.sub(r"^https?://(www\.)?", "", url)
    url = re.sub(r"[?#].*$", "", url)
    return url.rstrip("/")


def fingerprint(title: str) -> str:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return " ".join(words)


class Memory:
    def __init__(self, path: str | Path = ":memory:") -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # runs
    def start_run(self, run_id: str, goal: str) -> None:
        self.db.execute("INSERT INTO runs(run_id, started_at, goal) VALUES (?,?,?)", (run_id, _now(), goal))
        self.db.commit()

    def finish_run(self, run_id: str, stop_reason: str, steps: int, cost: float) -> None:
        self.db.execute("UPDATE runs SET finished_at=?, stop_reason=?, steps=?, cost_usd=? WHERE run_id=?",
                        (_now(), stop_reason, steps, cost, run_id))
        self.db.commit()

    # findings
    def find_existing(self, title: str, urls: list[str]) -> sqlite3.Row | None:
        for u in urls:
            row = self.db.execute(
                "SELECT f.* FROM finding_urls fu JOIN findings f USING(finding_id) WHERE fu.url=?",
                (normalize_url(u),)).fetchone()
            if row:
                return row
        return self.db.execute("SELECT * FROM findings WHERE fingerprint=?", (fingerprint(title),)).fetchone()

    def save_finding(self, run_id: str, title: str, why: str, urls: list[str], quote: str) -> dict:
        """Insert a new finding, or bump the sighting count on a known one."""
        existing = self.find_existing(title, urls)
        now = _now()
        if existing:
            same_run = existing["last_run_id"] == run_id
            if not same_run:
                self.db.execute(
                    "UPDATE findings SET sightings = sightings + 1, last_run_id=?, last_seen_at=? WHERE finding_id=?",
                    (run_id, now, existing["finding_id"]))
            self._link_urls(existing["finding_id"], urls)
            self.db.commit()
            row = self.db.execute("SELECT * FROM findings WHERE finding_id=?", (existing["finding_id"],)).fetchone()
            return {"status": "already_saved_this_run" if same_run else "seen_before", **self._row(row)}
        cur = self.db.execute(
            "INSERT INTO findings(fingerprint, title, why_it_matters, evidence_quote, source_urls,"
            " first_run_id, first_seen_at, last_run_id, last_seen_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (fingerprint(title), title, why, quote, json.dumps(urls), run_id, now, run_id, now))
        self._link_urls(cur.lastrowid, urls)
        self.db.commit()
        row = self.db.execute("SELECT * FROM findings WHERE finding_id=?", (cur.lastrowid,)).fetchone()
        return {"status": "new", **self._row(row)}

    def _link_urls(self, finding_id: int, urls: list[str]) -> None:
        for u in urls:
            self.db.execute("INSERT OR IGNORE INTO finding_urls(url, finding_id) VALUES (?,?)",
                            (normalize_url(u), finding_id))

    def recall(self, days: int = 90, query: str | None = None, limit: int = 30) -> list[dict]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        sql = "SELECT * FROM findings WHERE last_seen_at >= ?"
        args: list = [since]
        if query:
            sql += " AND (lower(title) LIKE ? OR lower(why_it_matters) LIKE ?)"
            args += [f"%{query.lower()}%"] * 2
        sql += " ORDER BY last_seen_at DESC LIMIT ?"
        args.append(limit)
        return [self._row(r) for r in self.db.execute(sql, args).fetchall()]

    def is_reported(self, url: str) -> bool:
        return self.db.execute("SELECT 1 FROM finding_urls WHERE url=?", (normalize_url(url),)).fetchone() is not None

    # change detection for web pages
    def page_changed(self, url: str, text: str) -> str:
        """Return 'first_time', 'changed' or 'unchanged', and store the new hash."""
        h = hashlib.sha256(text.encode()).hexdigest()
        row = self.db.execute("SELECT content_hash FROM page_hashes WHERE url=?", (normalize_url(url),)).fetchone()
        self.db.execute("INSERT OR REPLACE INTO page_hashes(url, content_hash, seen_at) VALUES (?,?,?)",
                        (normalize_url(url), h, _now()))
        self.db.commit()
        if row is None:
            return "first_time"
        return "unchanged" if row["content_hash"] == h else "changed"

    @staticmethod
    def _row(r: sqlite3.Row) -> dict:
        return {
            "finding_id": r["finding_id"], "title": r["title"], "why_it_matters": r["why_it_matters"],
            "source_urls": json.loads(r["source_urls"]), "first_seen_at": r["first_seen_at"],
            "last_seen_at": r["last_seen_at"], "sightings": r["sightings"],
        }
