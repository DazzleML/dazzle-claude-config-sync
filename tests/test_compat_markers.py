"""Every compatibility remnant is marked `COMPAT(remove-after: <trigger>)`
in its docstring, so the inventory is a grep rather than a memory.

The maintainer, 2026-09-05: "anything we keep that's for old compatibility
we should mark very clearly for removal later ... it should essentially be
a thin wrapper and all real logic should be implemented properly." This
test enumerates the markers, refuses one without a trigger, and pins the
inventory so a new remnant has to be registered here on purpose.
"""
from __future__ import annotations

import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "dazzle_claude_config"
MARK = re.compile(r"COMPAT\(remove-after:\s*([^)]*)\)")

#: file -> the triggers expected there. Add a line to add a remnant; delete
#: a line when the remnant goes.
EXPECTED = {
    "_vendor/ailib/analyzer.py": {
        "wtf locked migrates to build/run",     # analyze() and check_available(), the origin's front door
    },
    "airecord.py": {
        "one release with v2 records in the wild",   # the v1 record loader's branch (U5)
    },
}


def _found() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for p in PKG.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        for m in MARK.finditer(p.read_text(encoding="utf-8", errors="replace")):
            out.setdefault(str(p.relative_to(PKG)).replace("\\", "/"), set()).add(m.group(1).strip())
    return out


def test_every_marker_names_its_trigger():
    for rel, triggers in _found().items():
        for t in triggers:
            assert t, f"{rel}: a COMPAT marker with no remove-after trigger"


def test_the_inventory_is_exactly_what_is_registered():
    found = _found()
    expected = {k: v for k, v in EXPECTED.items() if (PKG / k).is_file()}
    assert found == expected, (
        f"compat remnants on disk: {found}; registered here: {expected}. Register a new "
        f"one (with its trigger) or delete the code the stale entry names.")
