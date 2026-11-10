"""The number check: every number in the brief must appear in some tool result from the run.

This is code, not a prompt. The model is told not to invent numbers; this checks that it
didn't, and flags any number it can't trace back to something the agent actually read.
"""

from __future__ import annotations

import re

_NUM = re.compile(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?%?")
_URL = re.compile(r"https?://\S+|\]\([^)]*\)")
_LIST_MARKER = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)


def _canon(token: str) -> str:
    t = token.replace("$", "").replace(",", "").rstrip("%").rstrip(".")
    if "." in t:
        whole, _, frac = t.partition(".")
        frac = frac.rstrip("0")
        whole = whole.lstrip("0") or "0"
        return f"{whole}.{frac}" if frac else whole
    return t.lstrip("0") or "0"


def numbers_in(text: str) -> list[str]:
    text = _URL.sub(" ", text)
    text = _LIST_MARKER.sub(" ", text)
    return [m.group(0).rstrip(".,") for m in _NUM.finditer(text)]


def check_numbers(brief: str, tool_results: list[str]) -> dict:
    """Return {"checked": n, "verified": [...], "unverified": [...]}."""
    seen: set[str] = set()
    for res in tool_results:
        # Tool results are JSON; unescape nothing fancy, just pull numbers out of the raw text.
        for m in _NUM.finditer(res):
            seen.add(_canon(m.group(0)))
    verified, unverified = [], []
    for tok in numbers_in(brief):
        (verified if _canon(tok) in seen else unverified).append(tok)
    return {"checked": len(verified) + len(unverified), "verified": verified,
            "unverified": sorted(set(unverified), key=unverified.index)}
