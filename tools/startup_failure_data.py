"""
Why startups fail: published survey data used across the app (no AI).

The numbers live in data/startup_failure_reasons.json with their source. They
were read from CB Insights' report "The top 9 reasons startups fail" (March 2026).
`verify_live()` fetches the report page and checks that the figures stated in
its text still match ours, so the app can show "checked against the source today".
"""

import json
import re
import time
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "startup_failure_reasons.json"
_TIMEOUT = 12
_CACHE_SECONDS = 6 * 3600
_last: Dict[str, Any] = {}

# How each stated figure is phrased in the report's text.
_PATTERNS = {
    "capital": r"[Rr]an out of capital[^.%]{0,60}?(\d{1,3})%",
    "pmf": r"product-market fit \((\d{1,3})%\)",
    "timing": r"bad timing \((\d{1,3})%\)",
    "economics": r"unit economics \((\d{1,3})%\)",
}


@lru_cache(maxsize=1)
def load() -> Dict[str, Any]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def check_text(page_text: str) -> Dict[str, Any]:
    """Compares the figures stated in the page text with the dataset."""
    data = load()
    text = re.sub(r"<[^>]+>", " ", page_text or "")
    text = re.sub(r"\s+", " ", text)
    rows = []
    for reason in data["reasons"]:
        pattern = _PATTERNS.get(reason["id"])
        if not pattern:
            continue
        match = re.search(pattern, text)
        found = int(match.group(1)) if match else None
        rows.append({"id": reason["id"], "reason": reason["reason"], "ours": reason["share"], "page": found,
                     "matches": found == reason["share"]})
    sample = re.search(r"(\d{3,4})\s+companies for which failure reasons could be identified", text)
    return {
        "checked": len(rows),
        "matching": sum(1 for r in rows if r["matches"]),
        "rows": rows,
        "sample_on_page": int(sample.group(1)) if sample else None,
    }


def verify_live() -> Dict[str, Any]:
    """Fetches the report page (cached for a few hours) and checks the stated figures."""
    if _last and time.time() - _last["at"] < _CACHE_SECONDS:
        return _last["result"]
    url = load()["source"]["url"]
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (academic project)"})
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            page = response.read(2_000_000).decode("utf-8", errors="replace")
        result = {"ok": True, "checked_at": time.strftime("%Y-%m-%d %H:%M"), **check_text(page)}
    except Exception as err:  # offline, blocked or changed page
        result = {"ok": False, "checked_at": time.strftime("%Y-%m-%d %H:%M"), "error": str(err)[:160]}
    _last.update(at=time.time(), result=result)
    return result
