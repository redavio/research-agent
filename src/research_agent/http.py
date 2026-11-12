"""HTTP fetch and HTML-to-text. Every failure becomes a FetchError with a plain message."""

from __future__ import annotations

import ipaddress
import re
import socket
from html import unescape
from html.parser import HTMLParser

import httpx

USER_AGENT = "Mozilla/5.0 (compatible; research-agent/0.1)"
TIMEOUT = 20.0


class FetchError(Exception):
    pass


def _public_host(host: str) -> bool:
    """True only when every address the host resolves to is on the public internet."""
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return True


def _guard(request: httpx.Request) -> None:
    # Runs on the first request and on every redirect, so a public page can't bounce the agent
    # onto a private address (matters when the agent runs on a server with visitor-typed URLs).
    if request.url.scheme not in ("http", "https") or not _public_host(request.url.host):
        raise FetchError(f"Not fetching {request.url}: only public web addresses are allowed")


def get(url: str, headers: dict | None = None, timeout: float = TIMEOUT) -> httpx.Response:
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, event_hooks={"request": [_guard]}) as client:
            resp = client.get(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    except httpx.HTTPError as e:
        raise FetchError(f"{type(e).__name__} fetching {url}: {e}") from e
    if resp.status_code >= 400:
        raise FetchError(f"HTTP {resp.status_code} from {url} (the site refused or the page is gone)")
    return resp


_SKIP = {"script", "style", "noscript", "svg", "head", "template", "iframe"}
_BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section",
          "article", "header", "footer", "ul", "ol", "table", "blockquote"}


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in _SKIP:
            self.skip += 1
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in _SKIP and self.skip:
            self.skip -= 1
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if not self.skip:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    """Return (title, readable text)."""
    if "<" not in html:
        return "", unescape(html).strip()
    parser = _TextParser()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - malformed HTML still yields what was parsed
        pass
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return parser.title.strip(), text.strip()
