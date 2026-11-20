"""The dashboard's contract with results.json and with apps that reuse its components.

The components in dashboard/src/components/ are shared: this repo's app and other apps (such as a
hosted portal) render them from the same typed result. So they take the result as props, never
fetch or read files themselves, and never import brand.ts (each app brands itself).
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASH = ROOT / "dashboard" / "src"


def interface_fields(name):
    """Field names of one `export interface <name> { ... }` in types.ts."""
    src = (DASH / "types.ts").read_text()
    body = re.search(r"export interface %s \{(.*?)\n\}" % name, src, re.S).group(1)
    return set(re.findall(r"^\s{2}(\w+)\??:", body, re.M))


def test_demo_results_match_types():
    res = json.loads((ROOT / "dashboard" / "public" / "results.json").read_text())
    assert set(res) == interface_fields("Results")


def test_components_take_props_only():
    files = sorted((DASH / "components").glob("*.tsx"))
    assert files, "dashboard/src/components/ is empty"
    for f in files:
        src = f.read_text()
        assert "fetch(" not in src, f"{f.name} fetches; pass the result in as props"
        assert not any("brand" in m for m in re.findall(r'from "([^"]+)"', src)), f"{f.name} imports brand.ts"
        assert "style={" not in src, f"{f.name} uses inline styles; use Tailwind classes"
