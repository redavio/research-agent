"""Source adapters. Each returns a list of items: {title, url, published, text}.

Adapters raise FetchError (or NotConfigured) on failure. They never swallow a failure into
an empty list, because "the source was quiet" and "the source is broken" must look different
to the agent.
"""

from __future__ import annotations

import base64
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlencode

import feedparser

from . import http
from .http import FetchError

MAX_TEXT = 20000


class NotConfigured(FetchError):
    """A source that needs credentials the user has not provided."""


def _iso(struct) -> str | None:
    if not struct:
        return None
    return datetime(*struct[:6], tzinfo=timezone.utc).isoformat()


def fetch_rss(src: dict) -> list[dict]:
    resp = http.get(src["url"])
    feed = feedparser.parse(resp.content)
    if feed.bozo and not feed.entries:
        raise FetchError(f"could not parse a feed at {src['url']}: {feed.bozo_exception}")
    items = []
    for e in feed.entries[:30]:
        body = ""
        if getattr(e, "content", None):
            body = e.content[0].get("value", "")
        body = body or getattr(e, "summary", "") or ""
        _, text = http.html_to_text(body)
        items.append({
            "title": getattr(e, "title", "") or "(untitled)",
            "url": getattr(e, "link", "") or src["url"],
            "published": _iso(getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)),
            "text": text[:MAX_TEXT],
        })
    return items


def fetch_web(src: dict) -> list[dict]:
    resp = http.get(src["url"])
    title, text = http.html_to_text(resp.text)
    if not text:
        raise FetchError(f"{src['url']} returned no readable text (page may need JavaScript)")
    return [{"title": title or src["url"], "url": str(resp.url), "aliases": [src["url"]],
             "published": None, "text": text[:MAX_TEXT]}]


YT_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"


def fetch_youtube(src: dict) -> list[dict]:
    cid = src.get("channel_id") or _resolve_channel_id(src["url"])
    feed = feedparser.parse(http.get(YT_FEED.format(cid=cid)).content)
    items = []
    for e in feed.entries[:6]:
        vid = getattr(e, "yt_videoid", None)
        desc = getattr(e, "summary", "") or ""
        transcript = _transcript(vid) if vid else ""
        items.append({
            "title": getattr(e, "title", "") or "(untitled video)",
            "url": getattr(e, "link", "") or f"https://www.youtube.com/watch?v={vid}",
            "published": _iso(getattr(e, "published_parsed", None)),
            "text": ((f"Transcript:\n{transcript}" if transcript else f"Description (no transcript available):\n{desc}"))[:MAX_TEXT],
        })
    return items


def _resolve_channel_id(url: str) -> str:
    m = re.search(r"channel/(UC[\w-]{20,})", url)
    if m:
        return m.group(1)
    html = http.get(url).text
    for pat in (r'"channelId":"(UC[\w-]{20,})"', r'channel/(UC[\w-]{20,})'):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    raise FetchError(f"could not find a YouTube channel id at {url}")


def _transcript(video_id: str) -> str:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # optional dependency
    except ImportError:
        return ""
    try:
        fetched = YouTubeTranscriptApi().fetch(video_id, languages=["en", "en-US", "en-GB"])
        return " ".join(s.text for s in fetched if s.text)
    except Exception:  # noqa: BLE001 - missing captions are normal
        return ""


REDDIT_TOKEN = "https://www.reddit.com/api/v1/access_token"


def fetch_reddit(src: dict) -> list[dict]:
    cid, secret = os.getenv("REDDIT_CLIENT_ID"), os.getenv("REDDIT_CLIENT_SECRET")
    if not (cid and secret):
        raise NotConfigured(
            "Reddit needs REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET (free 'script' app at "
            "https://www.reddit.com/prefs/apps). Not set, so this source was not read. "
            "This is not the same as the subreddit being quiet.")
    basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    try:
        import httpx
        tok = httpx.post(REDDIT_TOKEN, data={"grant_type": "client_credentials"},
                         headers={"Authorization": f"Basic {basic}", "User-Agent": http.USER_AGENT},
                         timeout=http.TIMEOUT).json().get("access_token")
    except Exception as e:  # noqa: BLE001
        raise FetchError(f"Reddit token request failed: {e}") from e
    if not tok:
        raise FetchError("Reddit rejected the credentials")
    sub = src["url"].rstrip("/").split("/r/")[-1]
    resp = http.get(f"https://oauth.reddit.com/r/{sub}/new?limit=25",
                    headers={"Authorization": f"Bearer {tok}"})
    items = []
    for ch in json.loads(resp.text).get("data", {}).get("children", []):
        d = ch.get("data", {})
        items.append({
            "title": d.get("title") or "(untitled)",
            "url": "https://www.reddit.com" + (d.get("permalink") or ""),
            "published": datetime.fromtimestamp(d["created_utc"], tz=timezone.utc).isoformat() if d.get("created_utc") else None,
            "text": f"{d.get('title')}\n\nr/{sub}: {d.get('score') or 0} upvotes, {d.get('num_comments') or 0} comments.\n\n{d.get('selftext') or ''}"[:MAX_TEXT],
        })
    return items


FETCHERS = {
    "rss": fetch_rss,
    "web": fetch_web,
    "youtube": fetch_youtube,
    "reddit": fetch_reddit,
}
