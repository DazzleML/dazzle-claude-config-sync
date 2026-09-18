"""`parsers` -- generic readers a caller chooses from. The library never
interprets an answer; it offers two ways to read one and the caller picks.

`json_block` is the reader ccs used from the facade (moved here, tests
ported). `sections` is the origin's labelled-prose splitter, generalised
to take its labels, with the `raw` fallback its caller depends on.
"""
from __future__ import annotations

import pytest

from dazzle_claude_config._vendor.ailib import parsers


# -- json_block ----------------------------------------------------------------------

def test_json_block_takes_the_last_fence():
    text = 'first ```json\n{"a": 1}\n``` then ```json\n{"a": 2}\n```'
    assert parsers.json_block(text) == {"a": 2}


@pytest.mark.parametrize("text", ["", "no fence at all", "```json\nnot json\n```", "```json\n```"])
def test_json_block_returns_none_when_absent_or_invalid(text):
    assert parsers.json_block(text) is None


def test_json_block_reads_a_multi_line_body():
    text = '```json\n{\n  "hunks": [\n    {"hunk": 1}\n  ]\n}\n```'
    assert parsers.json_block(text) == {"hunks": [{"hunk": 1}]}


def test_json_block_ignores_fences_of_other_languages():
    text = '```python\nprint(1)\n```\n```json\n{"ok": true}\n```\n```yaml\na: 1\n```'
    assert parsers.json_block(text) == {"ok": True}


# -- sections ------------------------------------------------------------------------------

PROSE = "What Happened: the box locked\nWhy: idle timeout\nWhat To Do: nothing\nConfidence: high"


def test_sections_with_the_default_labels_is_the_origins_shape():
    got = parsers.sections(PROSE)
    assert got == {"what_happened": "the box locked", "why": "idle timeout",
                   "what_to_do": "nothing", "confidence": "high"}


def test_sections_takes_its_labels_from_the_caller():
    got = parsers.sections("Summary: short\nDetail: long", [("summary", "Summary:"), ("detail", "Detail:")])
    assert got == {"summary": "short", "detail": "long"}


def test_sections_falls_back_to_raw_when_nothing_matches():
    assert parsers.sections("just prose, no labels") == {"raw": "just prose, no labels"}
