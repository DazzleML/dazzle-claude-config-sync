"""a5a -- one file through the AI step, end to end, paths in and files out.

`ai_step` takes the three sides of one file and the workspace path of the
person's `.merged` (never read, only used to name the proposal, the record
and the response file beside it), runs the diff3, builds the prompt, gets
an answer -- from a file the person carried back, from the workspace, or
from a backend through the facade -- checks it, assembles the proposal and
writes `<label>.merged-ai` with its record. It never touches `.merged`,
never installs anything, and never imports merge.py: the copy rule, the
validator and the report are the caller's.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dazzle_claude_config import aistep, airecord
from dazzle_claude_config.seeddecisions import norm_sha

BASE = b"# skill\nrule A\nrule B\n"
OURS = b"# skill\nrule A locally revised\nrule B\n"
THEIRS = b"# skill\nrule A revised upstream\nrule B\n"

GOOD = {"hunks": [{"hunk": 1, "lines": ["T1"], "rules": [], "rationale": "upstream's wording"}]}
BAD = {"hunks": [{"hunk": 1, "lines": ["O9"]}]}


def _world(tmp_path, ours=OURS, base=BASE, theirs=THEIRS):
    for name, data in (("ours", ours), ("base", base), ("theirs", theirs)):
        (tmp_path / name).write_bytes(data)
    ws = tmp_path / "ws"
    ws.mkdir()
    return dict(ours=tmp_path / "ours", base=tmp_path / "base", theirs=tmp_path / "theirs",
                merged=ws / "skills__s.md.merged", workdir=tmp_path / "work")


def _opts(tmp_path, **over):
    kw = dict(backend="prompt-only", rules_dir=tmp_path / "rules", prompts_dir=tmp_path / "prompts",
              cache_dir=tmp_path / "cache")
    kw.update(over)
    return aistep.AiOptions(**kw)


def _run(w, opts, **over):
    kw = dict(label="skills/s.md", ours=w["ours"], base=w["base"], theirs=w["theirs"],
              merged=w["merged"], opts=opts, workdir=w["workdir"])
    kw.update(over)
    return aistep.ai_step(**kw)


def test_a_one_sided_file_has_no_hunks_and_writes_nothing(tmp_path):
    w = _world(tmp_path, ours=BASE)          # only theirs moved
    out = _run(w, _opts(tmp_path))
    assert out.status == "no-hunks" and out.hunks == 0
    assert not airecord.proposal_path(w["merged"]).exists()
    assert not airecord.record_path(w["merged"]).exists()


def test_prompt_only_writes_the_prompt_and_names_the_response_file(tmp_path):
    w = _world(tmp_path)
    out = _run(w, _opts(tmp_path))
    assert out.status == "prompt-written" and out.hunks == 1
    written = list((tmp_path / "prompts").glob("skills__s.md-*.md"))
    assert len(written) == 1 and out.prompt_path == written[0]
    text = written[0].read_text(encoding="utf-8")
    assert "### Hunk 1 (paragraph)" in text and "T1: rule A revised upstream" in text
    assert out.response_path == airecord.response_path(w["merged"])
    assert out.reports and out.reports[0].startswith("hunk 1: both sides rewrote the same paragraph")
    assert "rules: none" in out.rules
    assert not airecord.proposal_path(w["merged"]).exists()


def test_a_canned_answer_proposes_and_records(tmp_path):
    w = _world(tmp_path)
    answer = tmp_path / "answer.json"
    answer.write_text(json.dumps(GOOD), encoding="utf-8")
    out = _run(w, _opts(tmp_path, response=answer))
    assert out.status == "proposed"
    proposal = airecord.proposal_path(w["merged"])
    assert out.proposal == proposal
    assert proposal.read_bytes() == b"# skill\nrule A revised upstream\nrule B\n"
    rec = airecord.load(airecord.record_path(w["merged"]))
    assert rec is not None and rec.valid and rec.failures == []
    assert rec.proposal_sha == norm_sha(proposal.read_bytes())
    assert rec.ours_sha == norm_sha(OURS) and rec.theirs_sha == norm_sha(THEIRS) and rec.base_sha == norm_sha(BASE)
    assert rec.backend == "prompt-only" and rec.base_kind == "inferred" and rec.copied_sha == ""
    assert out.rationales == [(1, [], "upstream's wording")]
    # the carried answer is kept beside the proposal for the record
    assert airecord.response_path(w["merged"]).read_text(encoding="utf-8") == json.dumps(GOOD)


def test_a_response_file_in_the_workspace_is_discovered(tmp_path):
    w = _world(tmp_path)
    airecord.response_path(w["merged"]).write_text(json.dumps(GOOD), encoding="utf-8")
    out = _run(w, _opts(tmp_path))
    assert out.status == "proposed"


def test_a_fenced_answer_is_read_like_a_bare_one(tmp_path):
    w = _world(tmp_path)
    answer = tmp_path / "answer.md"
    answer.write_text("Here you go:\n```json\n" + json.dumps(GOOD) + "\n```\n", encoding="utf-8")
    assert _run(w, _opts(tmp_path, response=answer)).status == "proposed"


def test_a_rejected_answer_records_the_failures_and_writes_no_proposal(tmp_path):
    w = _world(tmp_path)
    answer = tmp_path / "answer.json"
    answer.write_text(json.dumps(BAD), encoding="utf-8")
    out = _run(w, _opts(tmp_path, response=answer))
    assert out.status == "rejected"
    assert any("O9" in f for f in out.failures)
    assert not airecord.proposal_path(w["merged"]).exists()
    rec = airecord.load(airecord.record_path(w["merged"]))
    assert rec is not None and rec.valid is False and rec.failures == out.failures
    assert rec.proposal_sha == norm_sha(b"")     # N9: no proposal, so no proposal hash


def test_an_answer_with_no_json_is_rejected_and_says_so(tmp_path):
    w = _world(tmp_path)
    answer = tmp_path / "answer.txt"
    answer.write_text("I would keep both, honestly.", encoding="utf-8")
    out = _run(w, _opts(tmp_path, response=answer))
    assert out.status == "rejected" and any("JSON" in f for f in out.failures)


def test_the_rules_file_is_loaded_and_named(tmp_path):
    w = _world(tmp_path)
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "_default.md").write_text("TAKE upstream everywhere.\n", encoding="utf-8")
    out = _run(w, _opts(tmp_path))
    assert "_default.md" in out.rules and "(1 rule)" in out.rules
    assert "R1: TAKE upstream everywhere." in out.prompt_path.read_text(encoding="utf-8")


GOOD_REPLY = "Thinking...\n```json\n" + json.dumps(GOOD) + "\n```\n"


from dazzle_claude_config._vendor.ailib import backend as _backend_mod
from dazzle_claude_config._vendor.ailib.types import Readiness, Response


class _FakeTransport:
    """A fake TRANSPORT, installed under the name the claude and codex presets
    use ("cli"), so the real preset, the real Backend, the real cache and the
    real record all run and only the subprocess is faked. `calls` is the
    preset name per invocation; `model` is the spec's model the last call
    carried; `requests` holds every (spec, request) pair."""

    def __init__(self):
        self.calls: list[str] = []
        self.requests: list = []
        self.model = None
        self.ready = Readiness(True, "fake: its CLI was found")
        self.response = Response("answered", text=GOOD_REPLY, model_used="fake-model",
                                 honoured=("model", "schema"))

    def probe(self, spec):
        return self.ready

    def invoke(self, spec, req):
        self.calls.append(spec.name)
        self.requests.append((spec, req))
        self.model = spec.model
        return self.response

    def capabilities(self, spec):
        return frozenset({"model", "schema", "stream"})


@pytest.fixture
def fake(monkeypatch):
    t = _FakeTransport()
    _backend_mod.transport_for("cli")                  # load the builtins, then shadow one
    monkeypatch.setitem(_backend_mod._TRANSPORTS, "cli", t)
    return t


def test_a_live_backend_is_invoked_once_then_served_from_the_cache(tmp_path, fake):
    w = _world(tmp_path)
    out = _run(w, _opts(tmp_path, backend="claude"))
    assert out.status == "proposed" and out.backend == "claude" and out.cached is False
    assert fake.calls == ["claude"]
    assert list((tmp_path / "cache").glob("ccs-merge_claude_*.json"))   # {tool}_{preset}_{key}.json
    again = _run(w, _opts(tmp_path, backend="claude"))
    assert again.status == "proposed" and again.cached is True
    assert fake.calls == ["claude"]                         # not invoked again
    fresh = _run(w, _opts(tmp_path, backend="claude", refresh=True))
    assert fresh.cached is False and fake.calls == ["claude", "claude"]


def test_the_cache_key_changes_with_the_inputs(tmp_path, fake):
    w = _world(tmp_path)
    _run(w, _opts(tmp_path, backend="claude"))
    w["ours"].write_bytes(b"# skill\nrule A locally revised again\nrule B\n")
    _run(w, _opts(tmp_path, backend="claude"))
    assert fake.calls == ["claude", "claude"]


def test_a_backend_failure_writes_nothing_and_carries_the_error(tmp_path, fake):
    w = _world(tmp_path)
    fake.response = Response("failed", error="Claude CLI not found")
    out = _run(w, _opts(tmp_path, backend="claude"))
    assert out.status == "backend-failed" and "not found" in out.error
    assert not airecord.proposal_path(w["merged"]).exists()
    assert not airecord.record_path(w["merged"]).exists()


def test_an_unavailable_backend_is_refused_before_any_prompt(tmp_path, fake):
    w = _world(tmp_path)
    fake.ready = Readiness(False, "codex is not on PATH")
    out = _run(w, _opts(tmp_path, backend="codex"))
    assert out.status == "backend-failed" and "codex" in out.error and "not on PATH" in out.error
    assert fake.calls == []                                   # refused before any request
    assert not list((tmp_path / "prompts").glob("*")) if (tmp_path / "prompts").exists() else True


def test_an_explicit_response_beats_a_stale_workspace_answer(tmp_path):
    """Mutation survivor M1 (v0.5.21 sweep): the file the person named on
    the command line is the answer; a stale one in the workspace is not."""
    w = _world(tmp_path)
    airecord.response_path(w["merged"]).write_text(json.dumps(BAD), encoding="utf-8")
    answer = tmp_path / "answer.json"
    answer.write_text(json.dumps(GOOD), encoding="utf-8")
    out = _run(w, _opts(tmp_path, response=answer))
    assert out.status == "proposed"
    assert airecord.response_path(w["merged"]).read_text(encoding="utf-8") == json.dumps(GOOD)


def test_the_cache_key_changes_with_the_payload_side_and_the_rules(tmp_path, fake):
    """Mutation survivors M9/M10: every input the proposal was made from is
    in the key -- theirs and the rules file too, not only ours."""
    w = _world(tmp_path)
    _run(w, _opts(tmp_path, backend="claude"))
    w["theirs"].write_bytes(b"# skill\nrule A revised upstream again\nrule B\n")
    _run(w, _opts(tmp_path, backend="claude"))
    assert fake.calls == ["claude", "claude"]
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "_default.md").write_text("TAKE upstream everywhere.\n", encoding="utf-8")
    _run(w, _opts(tmp_path, backend="claude"))
    assert fake.calls == ["claude", "claude", "claude"]


def test_a_merge_file_failure_is_reported_not_parsed(tmp_path, monkeypatch):
    """Mutation survivor M12: git merge-file's 255 is an error, never a
    conflict count."""
    w = _world(tmp_path)
    monkeypatch.setattr(aistep.basefind, "merge_file_diff3", lambda *a, **k: ([], 255))
    out = _run(w, _opts(tmp_path))
    assert out.status == "backend-failed" and "merge-file" in out.error


def test_rationales_come_back_in_hunk_order(tmp_path):
    """Mutation survivor M14: the answer may list hunks in any order; the
    report reads them in file order."""
    w = _world(tmp_path, base=b"a\nkeep\nc\n", ours=b"a1\nkeep\nc1\n", theirs=b"a2\nkeep\nc2\n")
    answer = tmp_path / "answer.json"
    answer.write_text(json.dumps({"hunks": [
        {"hunk": 2, "lines": ["T1"], "rationale": "second"},
        {"hunk": 1, "lines": ["O1"], "rationale": "first"}]}), encoding="utf-8")
    out = _run(w, _opts(tmp_path, response=answer))
    assert out.status == "proposed" and out.hunks == 2
    assert [n for n, _, _ in out.rationales] == [1, 2]
    assert out.proposal.read_bytes() == b"a1\nkeep\nc2\n"


def test_the_cache_key_includes_the_ancestry_facts_and_the_base_kind(tmp_path, fake):
    """Mutation survivors N2/N3 (round 2): the structured facts the dossier
    is made from, and how the base was chosen, are part of what the
    proposal was made from."""
    w = _world(tmp_path)
    _run(w, _opts(tmp_path, backend="claude"), facts={"checkout_dirty": False})
    _run(w, _opts(tmp_path, backend="claude"), facts={"checkout_dirty": True})
    assert fake.calls == ["claude", "claude"]
    _run(w, _opts(tmp_path, backend="claude"), facts={"checkout_dirty": True}, base_kind="supplied")
    assert fake.calls == ["claude", "claude", "claude"]


def test_a_cache_entry_without_an_answer_falls_through_to_the_backend(tmp_path, fake):
    """Mutation survivor N6: a hit that carries no text is not an answer;
    the backend is asked, rather than an empty proposal or a KeyError."""
    import time
    w = _world(tmp_path)
    _run(w, _opts(tmp_path, backend="claude"))
    (f,) = (tmp_path / "cache").glob("ccs-merge_claude_*.json")
    f.write_text(json.dumps({"cached_at": time.time(), "response": {"text": ""}}), encoding="utf-8")
    out = _run(w, _opts(tmp_path, backend="claude"))
    assert out.status == "proposed" and out.cached is False and fake.calls == ["claude", "claude"]


def test_every_paragraph_hunk_gets_its_report(tmp_path):
    """Mutation survivor N11: the reports cover every hunk, not the first."""
    w = _world(tmp_path, base=b"a\nkeep\nc\n", ours=b"a1\nkeep\nc1\n", theirs=b"a2\nkeep\nc2\n")
    out = _run(w, _opts(tmp_path))
    assert any(l.startswith("hunk 1:") for l in out.reports)
    assert any(l.startswith("hunk 2:") for l in out.reports)


def test_prompt_only_never_touches_the_cache_or_a_backend(tmp_path, fake):
    w = _world(tmp_path)
    out = _run(w, _opts(tmp_path))
    assert out.status == "prompt-written" and fake.calls == []
    assert not (tmp_path / "cache").exists()


# -- the model reaches the backend, whichever backend it is ------------------

def test_the_configured_model_is_passed_to_the_backend(tmp_path, fake):
    """`ai_merge_model` was accepted by the config, documented, and reached
    ONLY the local server -- set it with a hosted backend and nothing
    happened. A setting that silently does nothing is the defect this whole
    release keeps finding; here it was ours."""
    w = _world(tmp_path)
    _run(w, _opts(tmp_path, backend="claude", model="some-model-alias"))
    assert fake.model == "some-model-alias"


def test_two_models_are_two_cache_entries(tmp_path, fake):
    """A different model is a different answerer, so it belongs in the key
    for every backend that can honour it -- otherwise changing the model
    returns the previous one's answer and the person concludes the setting
    was ignored (which, before this, it was)."""
    w = _world(tmp_path)
    _run(w, _opts(tmp_path, backend="claude", model="model-a"))
    assert fake.calls == ["claude"]
    _run(w, _opts(tmp_path, backend="claude", model="model-a"))
    assert fake.calls == ["claude"], "the same model should come from the cache"
    _run(w, _opts(tmp_path, backend="claude", model="model-b"))
    assert fake.calls == ["claude", "claude"], "a different model must not reuse it"


def test_every_preset_can_be_told_which_model_and_the_capability_says_so():
    """Once, codex could not be told a model: its flag was argv inside a
    copy we did not edit, and a table in the facade admitted it. Now the
    preset carries `-m {model}` and the backend's own capabilities say so --
    no table, nothing to keep in step."""
    from dazzle_claude_config import ailib
    for name in ("claude", "codex", "lmstudio", "openrouter"):
        assert "model" in ailib.build(ailib.spec_for(name)).capabilities, name
