"""analyze() -- the vendored library's ORIGINAL front door, kept as a thin
compatibility wrapper for the one live caller that still uses it:
`wtf locked --ai` (C:\\code\\wtf-windows\\tools\\core\\locked\\locked.py:349-359),
which imports `analyze` and `check_available` by name and passes
`refresh=args.ai_refresh`.

Slim on purpose (the maintainer, 2026-09-05: "a SLIM backwards compatibility
is fine ... it should essentially be a thin wrapper and all real logic should
be implemented properly"): the signature and the four-key result dict are
kept because the caller reads them; the body is `build` -> `probe` -> `run`
-> `parsers.sections`, nothing of its own. Marked COMPAT(remove-after: wtf
locked migrates to build/run); tests/test_compat_markers.py holds the
inventory.

U0 (2026-09-05) fixed the original body's UnboundLocalError on
refresh=True; U4 replaced the body. The call shape below is the origin's
and must keep working either way.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dazzle_claude_config._vendor.ailib import analyzer
from dazzle_claude_config._vendor.ailib import backend as _backend_mod
from dazzle_claude_config._vendor.ailib.types import Readiness, Response

# The origin's response shape: labelled sections with a colon (DEFAULT_SECTIONS
# in analyzer.py), which is what `wtf locked`'s prompt template asks for.
PROSE = "What Happened: lock\nWhy: idle\nWhat To Do: nothing\nConfidence: high"


class _FakeTransport:
    """Installed under "cli", the transport the shim's claude/codex specs use."""

    def __init__(self):
        self.calls = 0
        self.ready = Readiness(True, "fake: its CLI was found")
        self.response = Response("answered", text=PROSE, model_used="fake")

    def probe(self, spec):
        return self.ready

    def invoke(self, spec, req):
        self.calls += 1
        self.last = req
        return self.response

    def capabilities(self, spec):
        return frozenset({"stream"})


@pytest.fixture
def fake(monkeypatch):
    t = _FakeTransport()
    _backend_mod.transport_for("cli")
    monkeypatch.setitem(_backend_mod._TRANSPORTS, "cli", t)
    return t


def _locked_style_call(tmp_path: Path, **over):
    """The exact call shape locked.py makes, with a template that uses the
    same placeholder its diagnose.md does."""
    tpl = tmp_path / "diagnose.md"
    tpl.write_text("Evidence:\n{evidence_json}\n", encoding="utf-8")
    kw = dict(results={"raw": {"event": "lock"}},
              fingerprint_fn=lambda r: {"event": r["raw"]["event"]},
              prompt_path=tpl, cache_dir=tmp_path / "cache", tool_name="locked",
              backend_name="claude", verbose=False, timeout=120, refresh=False)
    kw.update(over)
    return analyzer.analyze(**kw)


def test_the_origins_call_shape_answers_with_four_sections(tmp_path, fake):
    out = _locked_style_call(tmp_path)
    assert out["success"] is True and out["error"] is None
    assert set(out["sections"]) == {"what_happened", "why", "what_to_do", "confidence"}
    assert out["raw_response"] == PROSE
    assert "evidence_json" not in fake.last.prompt and '"event": "lock"' in fake.last.prompt


def test_refresh_returns_an_answer_instead_of_raising(tmp_path, fake):
    out = _locked_style_call(tmp_path, refresh=True)
    assert out["success"] is True and out["error"] is None


def test_refresh_still_writes_the_cache_so_the_next_call_is_a_hit(tmp_path, fake):
    _locked_style_call(tmp_path, refresh=True)
    files = list((tmp_path / "cache").glob("locked_claude_*.json"))
    assert len(files) == 1, "refresh must re-ask AND re-cache"
    again = _locked_style_call(tmp_path)
    assert again.get("cached") is True and again["cached_at"] > 0 and fake.calls == 1


def test_the_origins_result_keys_are_preserved(tmp_path, fake):
    """locked embeds this dict in its --json output; the keys are user-visible."""
    out = _locked_style_call(tmp_path)
    assert set(out) == {"success", "raw_response", "sections", "error"}
    hit = _locked_style_call(tmp_path)
    assert set(hit) == {"success", "raw_response", "sections", "error", "cached", "cached_at"}


def test_a_failed_backend_is_the_origins_failure_shape(tmp_path, fake):
    fake.response = Response("failed", error="Claude CLI exited with code 1")
    out = _locked_style_call(tmp_path)
    assert out["success"] is False and out["error"] == out["raw_response"] == "Claude CLI exited with code 1"
    assert out["sections"] == {}
    assert not list((tmp_path / "cache").glob("*.json"))


def test_an_unavailable_backend_says_so_before_any_prompt(tmp_path, fake):
    fake.ready = Readiness(False, "claude is not on PATH")
    out = _locked_style_call(tmp_path)
    assert out["success"] is False and "not available" in out["error"] and "not on PATH" in out["error"]
    assert fake.calls == 0


def test_prompt_only_defers_with_the_origins_sentence(tmp_path, monkeypatch):
    monkeypatch.setitem(analyzer._COMPAT_PRESETS, "prompt-only",
                        analyzer._COMPAT_PRESETS["prompt-only"].with_(endpoint=str(tmp_path / "ai")))
    out = _locked_style_call(tmp_path, backend_name="prompt-only")
    assert out["success"] is False and out["error"].startswith("Prompt saved to:")
    saved = Path(out["error"].split("Prompt saved to:", 1)[1].strip())
    assert saved.is_file() and '"event": "lock"' in saved.read_text(encoding="utf-8")
    assert not list((tmp_path / "cache").glob("*.json"))     # nothing to cache


def test_an_unknown_name_is_the_origins_error_not_an_exception(tmp_path, fake):
    out = _locked_style_call(tmp_path, backend_name="gpt9")
    assert out["success"] is False and "gpt9" in out["error"] and "claude" in out["error"]


def test_check_available_answers_by_name_through_the_object_model(fake):
    assert analyzer.check_available("claude") is True
    fake.ready = Readiness(False, "no")
    assert analyzer.check_available("codex") is False
    assert analyzer.check_available("no-such") is False
