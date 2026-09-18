"""Readers a caller chooses from. The library never interprets an answer; it
offers two ways to read one and the caller picks the one its prompt asked
for. A merge tool wants one fenced JSON object; a diagnostic tool wants
labelled prose sections. Neither shape is this library's.
"""
from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```json\s*\n(.*?)\n\s*```", re.DOTALL)

#: The labelled-prose shape the original diagnostic tools ask for.
DEFAULT_SECTIONS: list[tuple[str, str]] = [
    ("what_happened", r"What Happened:"),
    ("why", r"Why:"),
    ("what_to_do", r"What To Do:"),
    ("confidence", r"Confidence:"),
]


def json_block(text: str) -> Any | None:
    """The LAST fenced ```json block in `text`, parsed; None when there is
    none or it does not parse. The last one, because a model that thinks
    aloud tends to draft and then answer."""
    blocks = _FENCE.findall(text or "")
    if not blocks:
        return None
    try:
        return json.loads(blocks[-1])
    except ValueError:
        return None


def sections(text: str, labels: list[tuple[str, str]] | None = None) -> dict[str, str]:
    """Split labelled prose into a dict by the caller's labels -- each a
    (key, regex) pair, in the order they appear. When nothing matches, the
    whole text comes back under "raw", so a caller always has something to
    show."""
    labels = labels or DEFAULT_SECTIONS
    out: dict[str, str] = {}
    for i, (key, pattern) in enumerate(labels):
        rest = [p for _, p in labels[i + 1:]]
        regex = (rf"{pattern}\s*(.*?)(?=(?:{'|'.join(rest)})|\Z)" if rest
                 else rf"{pattern}\s*(.*)")
        m = re.search(regex, text or "", re.DOTALL)
        if m:
            out[key] = m.group(1).strip()
    if not out:
        out["raw"] = (text or "").strip()
    return out
