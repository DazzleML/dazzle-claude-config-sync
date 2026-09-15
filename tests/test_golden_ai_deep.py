"""The golden set for the deep merge (#64): clean merges with known-right
answers, judged the way the maintainer judges them.

Pass 1's golden set (test_golden_ai_merge.py) judges the recipe on
CONFLICT-HUNKS: regions both sides changed, where git writes three panes and
a model picks lines. This set judges the deep step on DIFF-HUNKS: regions
one side changed and git took on its own, where the merge is textually
clean and may still be wrong. Every fixture here merges clean by
construction (a test proves it), so the recipe has nothing to decide and
the deep step reads git's own result for meaning.

Each fixture is three sides of one file, the mechanical result git
produces, the answer a model SHOULD give (files to write in the sandbox for
the tools form; the same answer as a unified diff for the no-tools form,
derived from the expected text), the rung that answer needs, the status the
step must reach at each scope tried, and what the report must say.

Two modes over the same fixtures:

  canned -- always runs. The real command runs over fake transports that
            answer as scripted, so the pipeline from answer to variant --
            sandbox, capture, the ladder verdict, the record, the report --
            is proven before any model is asked. Green here means the
            fixture is coherent.
  live   -- runs only when CCS_GOLDEN_AI names a preset. The backend is
            asked for real at each scope the fixture lists, the variant is
            compared to the expected text, and one matrix line per case is
            printed for the witnessed runs' record:

                GOLDEN-DEEP | <preset> | <fixture> | scope=<where> form=<tools|no-tools> | <verdict>

            scope and form are separate words on purpose (the latitude
            design of 2026-09-15, move N2): a later freedom word slots in
            beside them. A miss is a finding the person judges, not a
            defect: the expected text is one right answer, not the only one.

The b()/c() case is the maintainer's own (tests/bc_fixture.py, shared with
the rung classifier's tests so the two agree on every byte).
"""
from __future__ import annotations

import difflib
import json
import os
import re
import subprocess as sp
from pathlib import Path

import pytest

from bc_fixture import (BASE, FIXED_BROKEN, FIXED_IN_A, MERGED_BROKEN, MERGED_FINE, OURS,
                        THEIRS_BROKEN, THEIRS_FINE)
from conftest import GIT_ID

from dazzle_claude_config import airecord, airung, basefind, merge
from dazzle_claude_config.cli import EXIT_CLEAN, EXIT_DRIFT, main

from test_merge_ai import MANIFEST, _ccs

# bc_fixture holds text; this set stores bytes, like the recipe's golden set
BASE, OURS, THEIRS_BROKEN, THEIRS_FINE, MERGED_BROKEN, MERGED_FINE, FIXED_BROKEN, FIXED_IN_A = (
    s.encode("utf-8") for s in (BASE, OURS, THEIRS_BROKEN, THEIRS_FINE, MERGED_BROKEN, MERGED_FINE,
                                FIXED_BROKEN, FIXED_IN_A))


def _lf(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


# -- the Markdown runbook: two diff-hunks in different sections ------------------------
#
# Bob adds a step that cites "the report"; Charlie renames the report to
# "the summary" in another section. Git takes both. Nothing conflicts, and
# the runbook now tells the reader to open a file by a name it no longer has.

BASE_MD = b"""# Runbook

## Terms

The report is the file `out.md`.
It is regenerated on every build.

## Steps

1. Run the build.
2. Check the log.

## Notes

Nothing yet.
"""
OURS_MD = BASE_MD.replace(b"2. Check the log.\n", b"2. Check the log.\n3. Open the report.\n")
THEIRS_MD = BASE_MD.replace(b"The report is the file", b"The summary is the file")
THEIRS_FINE_MD = BASE_MD.replace(b"It is regenerated on every build.",
                                 b"It is regenerated on every build and kept beside the log.")
#: git's clean merge of OURS_MD and THEIRS_MD -- both diff-hunks taken, no markers
MERGED_MD = THEIRS_MD.replace(b"2. Check the log.\n", b"2. Check the log.\n3. Open the report.\n")
MERGED_FINE_MD = THEIRS_FINE_MD.replace(b"2. Check the log.\n", b"2. Check the log.\n3. Open the report.\n")
#: the rung-1 fix: the new step follows the rename; nothing else moves
FIXED_MD = MERGED_MD.replace(b"3. Open the report.", b"3. Open the summary.")
#: a fix in a section neither side touched: rung 2
NOTES_FIXED_MD = MERGED_MD.replace(b"Nothing yet.", b"The report was renamed to the summary; step 3 still says report.")
#: a fix by deletion: Bob's step is dropped rather than reworded -- a line one side
#: wrote is gone, which is exactly what the loss check looks for (C8: a tripwire)
DROPPED_MD = MERGED_MD.replace(b"3. Open the report.\n", b"")

PY = "s.py"
MD = "s.md"


def _answer(summary: str, *edits: tuple[str, str, str]) -> dict:
    return {"summary": summary, "edits": [{"path": p, "region": r, "reason": why} for p, r, why in edits]}


# -- the fixtures ------------------------------------------------------------------------
#
# name: the payload file (its suffix picks the region splitter); base / ours /
# theirs: the three sides; mechanical: git's clean merge (a test proves it);
# writes: sandbox-relative files the tools form writes -- the payload is
# `checkout/dotclaude/skills/<name>`; expected: the variant's text (None when
# the right answer is no change); scopes: the status the step must reach at
# each scope tried; needed: the rung the answer needs; answer: the model's
# closing JSON; report: substrings the report must print, per scope.

def _payload(name: str) -> str:
    return f"checkout/dotclaude/skills/{name}"


FIXTURES: dict[str, dict] = {
    "bc-python-broken": dict(
        cells="the founding case: b() doubles what c() returns, c() now returns a pair; two diff-hunks, clean, wrong",
        name=PY, base=BASE, ours=OURS, theirs=THEIRS_BROKEN, mechanical=MERGED_BROKEN,
        writes={_payload(PY): FIXED_BROKEN}, expected=FIXED_BROKEN,
        scopes={"hunk": "deep-proposed"}, needed="hunk",
        answer=_answer("b() now adapts to the tuple c() returns",
                       (PY, "b", "c() returns a pair now; doubling a tuple repeats it")),
        report={"hunk": ["b (rung 1): c() returns a pair now", "needed: hunk", "files touched: 1"]}),

    "bc-python-control": dict(
        cells="the control: c() still returns an int; two diff-hunks, clean, right -- the answer is no change",
        name=PY, base=BASE, ours=OURS, theirs=THEIRS_FINE, mechanical=MERGED_FINE,
        writes={}, expected=None,
        scopes={"hunk": "deep-empty"}, needed="none",
        answer=_answer("nothing needed changing: b() doubles an int as before"),
        report={"hunk": ["nothing to change"]}),

    "bc-python-fix-in-a": dict(
        cells="the same defect fixed in a(), which neither side touched: rung 2, refused at hunk, kept at file",
        name=PY, base=BASE, ours=OURS, theirs=THEIRS_BROKEN, mechanical=MERGED_BROKEN,
        writes={_payload(PY): FIXED_IN_A}, expected=FIXED_IN_A,
        scopes={"hunk": "deep-failed", "file": "deep-proposed"}, needed="file",
        answer=_answer("a() unwraps the pair b() now returns",
                       (PY, "a", "b() hands back a pair since c() changed; a() takes the first")),
        report={"hunk": ["NOT KEPT", "needed file", "hunk was allowed", "rung 2"],
                "file": ["a (rung 2): b() hands back a pair", "needed: file"]}),

    "bc-markdown-broken": dict(
        cells="Markdown: a step added under one heading cites a term renamed under another; the fix in Steps is rung 1",
        name=MD, base=BASE_MD, ours=OURS_MD, theirs=THEIRS_MD, mechanical=MERGED_MD,
        writes={_payload(MD): FIXED_MD}, expected=FIXED_MD,
        scopes={"hunk": "deep-proposed"}, needed="hunk",
        # the reason names the region alone, as a model answering about one
        # file may: it must land on the edit by region, case-insensitively,
        # with no path to fall back on
        answer={"summary": "the new step now names the file the way Terms does",
                "edits": [{"region": "Steps",
                           "reason": "Terms renamed the report to the summary; the added step still said report"}]},
        report={"hunk": ["Steps (rung 1): Terms renamed the report", "needed: hunk"]}),

    "bc-markdown-control": dict(
        cells="Markdown control: the other side's change does not contradict the added step; no change is right",
        name=MD, base=BASE_MD, ours=OURS_MD, theirs=THEIRS_FINE_MD, mechanical=MERGED_FINE_MD,
        writes={}, expected=None,
        scopes={"hunk": "deep-empty"}, needed="none",
        answer=_answer("the two changes agree; nothing to do"),
        report={"hunk": ["nothing to change"]}),

    "rung-2-other-section": dict(
        cells="the fix lands in a section neither side touched (Notes): rung 2 -- refused at hunk, kept at file",
        name=MD, base=BASE_MD, ours=OURS_MD, theirs=THEIRS_MD, mechanical=MERGED_MD,
        writes={_payload(MD): NOTES_FIXED_MD}, expected=NOTES_FIXED_MD,
        scopes={"hunk": "deep-failed", "file": "deep-proposed"}, needed="file",
        answer=_answer("a note explains the rename rather than editing the step",
                       (MD, "Notes", "recorded the rename where a reader will look")),
        report={"hunk": ["NOT KEPT", "needed file", "hunk was allowed", "rung 2"],
                "file": ["Notes (rung 2): recorded the rename", "needed: file"]}),

    "rung-3-neighbour-file": dict(
        cells="the fix also edits a neighbour in the same component (helper.md): rung 3 -- refused at file, kept at neighbours; tools only",
        name=MD, base=BASE_MD, ours=OURS_MD, theirs=THEIRS_MD, mechanical=MERGED_MD,
        writes={_payload(MD): FIXED_MD,
                "checkout/dotclaude/skills/helper.md": b"helper: notes the payload does not cite\nthe report is now the summary\n"},
        expected=FIXED_MD,
        scopes={"file": "deep-failed", "neighbours": "deep-proposed"}, needed="neighbours",
        # the middle entry is a note the model made about a region it did not
        # edit, with no path: it must attach to no edit line in the report
        answer={"summary": "the step and the helper both follow the rename",
                "edits": [{"path": MD, "region": "Steps", "reason": "Terms renamed the report"},
                          {"region": "Terms", "reason": "the rename itself is Charlie's and stands"},
                          {"path": "helper.md", "region": "", "reason": "the helper cited the old name"}]},
        report={"file": ["NOT KEPT", "needed neighbours", "file was allowed", "helper.md", "rung 3"],
                "neighbours": ["files touched: 2", "needed: neighbours", "helper.md (rung 3): the helper cited the old name"]}),

    "rung-4-far-file": dict(
        cells="the fix also edits a file outside the component (checkout/README.md): rung 4 -- refused at neighbours, kept at project; tools only",
        name=MD, base=BASE_MD, ours=OURS_MD, theirs=THEIRS_MD, mechanical=MERGED_MD,
        writes={_payload(MD): FIXED_MD, "checkout/README.md": b"a far file\nthe runbook's report is the summary now\n"},
        expected=FIXED_MD,
        scopes={"neighbours": "deep-failed", "project": "deep-proposed"}, needed="project",
        answer=_answer("the step and the README both follow the rename",
                       (MD, "Steps", "Terms renamed the report"), ("README.md", "", "the README cited the old name")),
        report={"neighbours": ["NOT KEPT", "needed project", "neighbours was allowed", "README.md", "rung 4"],
                "project": ["files touched: 2", "needed: project", "README.md"]}),

    "tripwire-drop": dict(
        cells="a fix by deletion: Bob's added step is dropped, so a line one side wrote is gone -- kept at hunk, and the loss check is a tripwire at --accept, never a refusal (C8)",
        name=MD, base=BASE_MD, ours=OURS_MD, theirs=THEIRS_MD, mechanical=MERGED_MD,
        writes={_payload(MD): DROPPED_MD}, expected=DROPPED_MD,
        scopes={"hunk": "deep-proposed"}, needed="hunk",
        answer=_answer("dropped the step that named a file which no longer exists",
                       (MD, "Steps", "the step pointed at a name Terms retired")),
        report={"hunk": ["Steps (rung 1)", "needed: hunk"]}),
}

ALL = dict(FIXTURES)


# -- the cases: fixture x scope x form ---------------------------------------------------

def _rung(token: str) -> int:
    return airung.rung_of(token)


def _cases() -> list[tuple[str, str, str, str]]:
    """(fixture, scope, form, status). The no-tools form runs a fixture whose
    answer touches only the payload file; at neighbours or project it must be
    refused before any call ("refused"), whatever the fixture."""
    out = []
    for name, fx in ALL.items():
        single_file = all(p == _payload(fx["name"]) for p in fx["writes"])
        for scope, status in fx["scopes"].items():
            out.append((name, scope, "tools", status))
            if _rung(scope) >= 3:
                out.append((name, scope, "no-tools", "refused"))
            elif single_file:
                out.append((name, scope, "no-tools", status))
    return out


CASES = _cases()


@pytest.fixture(params=CASES, ids=[f"{n}@{s}/{f}" for n, s, f, _ in CASES])
def case(request):
    return request.param


# -- a world: a checkout with a neighbour and a far file, and the live component ---------

def _git(cwd: Path, *args: str) -> None:
    r = sp.run(["git", *GIT_ID, "-C", str(cwd), *args], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, f"git {args}: {r.stderr}"


def _world(tmp_path: Path, fx: dict) -> dict:
    """The checkout holds the payload at the base then at theirs (HEAD), a
    neighbour in the same component and a far file, all committed (the
    sandbox is a worktree of HEAD, so an uncommitted neighbour would not be
    in it); the live root holds ours and the neighbour."""
    name = fx["name"]
    co, live, user = tmp_path / "co", tmp_path / "live", tmp_path / "user"
    (co / "dotclaude" / "skills").mkdir(parents=True)
    (live / "skills").mkdir(parents=True)
    user.mkdir()
    (co / "ccs-manifest.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    sp.run(["git", "init", "-q", "-b", "main", str(co)], check=True)
    (co / "dotclaude" / "skills" / name).write_bytes(fx["base"])
    (co / "dotclaude" / "skills" / "helper.md").write_text("helper: notes the payload does not cite\n", encoding="utf-8")
    (co / "README.md").write_text("a far file\n", encoding="utf-8")
    _git(co, "add", "-A")
    _git(co, "commit", "-qm", "base")
    (co / "dotclaude" / "skills" / name).write_bytes(fx["theirs"])
    _git(co, "commit", "-qam", "theirs")
    (live / "skills" / name).write_bytes(fx["ours"])
    (live / "skills" / "helper.md").write_text("helper: notes the payload does not cite\n", encoding="utf-8")
    ws = user / "merge" / "ccs"
    return dict(co=co, live=live, user=user, ws=ws, name=name, label=f"skills/{name}",
                merged=ws / f"skills__{name}.merged", live_file=live / "skills" / name)


# -- the fake transports ---------------------------------------------------------------------

def _diff(name: str, before: bytes, after: bytes) -> str:
    """The no-tools answer, derived: a unified diff from git's merge to the
    expected text, in the headers the step's `git apply` expects."""
    a = before.decode("utf-8").splitlines(keepends=True)
    b = after.decode("utf-8").splitlines(keepends=True)
    return "".join(difflib.unified_diff(a, b, fromfile=f"a/{name}", tofile=f"b/{name}"))


class _Tools:
    """A fake `cli` transport with tools: writes the fixture's files into the
    sandbox and closes with the fixture's JSON. The recipe must never call it
    -- a deep golden fixture merges clean, so there is no conflict-hunk."""
    writes: dict[str, bytes] = {}
    answer: dict = {}
    calls: list[str] = []

    def probe(self, spec):
        from dazzle_claude_config._vendor.ailib.types import Readiness
        return Readiness(True, "its CLI was found: C:/fake/claude.exe", warning="")

    def capabilities(self, spec):
        return frozenset({"model", "stream", "tools"})

    def invoke(self, spec, req):
        from dazzle_claude_config._vendor.ailib.types import Response
        assert "the deep step" in req.prompt.splitlines()[0], "a deep golden fixture merges clean: the recipe never asks"
        assert req.workdir, "the tools form runs in the sandbox"
        _Tools.calls.append("deep")
        for rel, content in _Tools.writes.items():
            p = Path(req.workdir) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
        return Response("answered", text="Done.\n```json\n" + json.dumps(_Tools.answer) + "\n```\n",
                        model_used="fake-opus", honoured=("model", "tools"))


class _NoTools:
    """A fake `openai_compat` transport: no tools; answers the deep prompt
    with the fixture's diff (empty when the right answer is no change)."""
    diff: str = ""
    answer: dict = {}
    calls: list[str] = []

    def probe(self, spec):
        from dazzle_claude_config._vendor.ailib.types import Readiness
        return Readiness(True, "http://fake/v1 -- reachable, model fake-27b", warning="")

    def capabilities(self, spec):
        return frozenset({"model", "schema"})

    def invoke(self, spec, req):
        from dazzle_claude_config._vendor.ailib.types import Response
        assert "the deep step" in req.prompt.splitlines()[0], "a deep golden fixture merges clean: the recipe never asks"
        assert not req.workdir, "the no-tools form never names a workdir"
        _NoTools.calls.append("deep")
        return Response("answered", text="```diff\n" + _NoTools.diff + "```\n\n```json\n"
                                         + json.dumps(_NoTools.answer) + "\n```\n",
                        model_used="fake-27b", honoured=("model",))


@pytest.fixture
def fakes(monkeypatch):
    from dazzle_claude_config._vendor.ailib import backend as _bm
    _bm.transport_for("cli")
    monkeypatch.setitem(_bm._TRANSPORTS, "cli", _Tools())
    monkeypatch.setitem(_bm._TRANSPORTS, "openai_compat", _NoTools())
    _Tools.writes, _Tools.answer, _Tools.calls = {}, {}, []
    _NoTools.diff, _NoTools.answer, _NoTools.calls = "", {}, []
    monkeypatch.delenv("CCS_AI_MERGE_BACKEND", raising=False)


def _script(fx: dict, form: str) -> str:
    """Load the fakes with this fixture's answer; return the preset to name."""
    if form == "tools":
        _Tools.writes, _Tools.answer = dict(fx["writes"]), fx["answer"]
        return "claude"
    _NoTools.diff = _diff(fx["name"], fx["mechanical"], fx["expected"]) if fx["expected"] is not None else ""
    _NoTools.answer = fx["answer"]
    return "lmstudio"


def _run(w: dict, preset: str, scope: str) -> int:
    return main(_ccs(w, "merge", w["label"], "--ai", f"{preset},deep", "--ai-scope", scope, "--no-launch"))


# -- the canned runner -------------------------------------------------------------------------

NO_TOOLS_SUFFIX = "no tools: the model saw this file and the two diffs only"


def _check(w: dict, fx: dict, scope: str, status: str, out: str, rc: int, form: str) -> None:
    variant = airecord.proposal_path(w["merged"], 1)
    assert not airecord.proposal_path(w["merged"]).exists(), "a clean merge writes no bare .merged-ai"
    if status == "deep-proposed":
        assert rc == EXIT_CLEAN, out
        assert variant.is_file(), f"no variant was staged:\n{out}"
        # the guarantees line says which form answered: the live runner reads the form off it
        assert (NO_TOOLS_SUFFIX in out) == (form == "no-tools"), out
        got = _lf(variant.read_bytes())
        assert got == _lf(fx["expected"]), (
            f"variant differs from the golden text:\n--- got ---\n{got.decode('utf-8', 'replace')}"
            f"\n--- expected ---\n{fx['expected'].decode('utf-8', 'replace')}\n--- report ---\n{out}")
        rec = airecord.load(airecord.record_path(w["merged"]))
        assert rec is not None and rec.chosen == 0, "chosen never moves on a run"
        assert [airecord.answer_kind(a) for a in rec.answers] == ["mechanical", "deep"]
        assert rec.answers[1]["scope"] == {"allowed": _rung(scope), "needed": _rung(fx["needed"])}
        assert f"needed: {fx['needed']}" in out and ".merged-ai.1" in out
        assert _lf(w["merged"].read_bytes()) == _lf(fx["mechanical"]), "the copy rule: git's result, never the deep variant"
    elif status == "deep-empty":
        assert rc == EXIT_CLEAN, out
        assert not variant.exists(), f"a variant was staged for an empty change:\n{out}"
    elif status == "deep-failed":
        assert rc == EXIT_DRIFT, out
        assert not variant.exists(), f"a variant was kept beyond the allowed scope:\n{out}"
        assert f"NOT KEPT {w['label']}" in out and f"needed {fx['needed']}" in out and f"{scope} was allowed" in out
    elif status == "refused":
        assert not variant.exists()
        assert "has no tools" in out and "rung 2 (file)" in out, out
    assert _lf(w["live_file"].read_bytes()) == _lf(fx["ours"]), "nothing is ever installed by a run"
    for s in fx.get("report", {}).get(scope, []) if status != "refused" else []:
        assert s in out, f"report lacks {s!r}:\n{out}"


def test_canned(tmp_path, capsys, fakes, case):
    """The fixture is coherent: the scripted answer, through the real command
    and the real sandbox, reaches the status the fixture names at this scope,
    and the variant is the expected text."""
    name, scope, form, status = case
    fx = ALL[name]
    w = _world(tmp_path, fx)
    preset = _script(fx, form)
    rc = _run(w, preset, scope)
    out = capsys.readouterr().out
    calls = _Tools.calls if form == "tools" else _NoTools.calls
    assert calls == ([] if status == "refused" else ["deep"]), (calls, out)   # the recipe never asked
    _check(w, fx, scope, status, out, rc, form)


def test_the_tripwire_drop_is_printed_at_accept_and_installs(tmp_path, capsys, fakes, monkeypatch):
    """C8 over a golden fixture: the dropped step is a line one side wrote,
    which the loss check sees; at --accept it is said out loud and does not
    refuse, because a deep answer may drop what it judges wrong."""
    fx = ALL["tripwire-drop"]
    w = _world(tmp_path, fx)
    _script(fx, "tools")
    assert _run(w, "claude", "hunk") == EXIT_CLEAN
    capsys.readouterr()
    w["merged"].write_bytes(fx["expected"])                       # the person puts the variant in .merged
    monkeypatch.setattr(merge, "_ask_ai_on_console", lambda item, rec: True)
    rc = main(_ccs(w, "merge", w["label"], "--accept", "--no-launch"))
    out = capsys.readouterr().out
    assert rc == EXIT_CLEAN, out
    assert f"tripwire {w['label']}" in out and "may contain text no side wrote" in out
    assert _lf(w["live_file"].read_bytes()) == _lf(fx["expected"])   # printed, not refused


# -- the live runner ---------------------------------------------------------------------------

LINE_SHAPE = re.compile(r"^GOLDEN-DEEP \| [^|]+ \| [^|]+ \| scope=(hunk|file|neighbours|project) "
                        r"form=(tools|no-tools) \| .+$")


def _line(preset: str, model: str, name: str, scope: str, form: str, verdict: str) -> str:
    """One matrix line: scope and form are separate words so a later
    freedom word slots in beside them (latitude design, N2)."""
    who = f"{preset} {model}" if model else preset
    return f"GOLDEN-DEEP | {who} | {name} | scope={scope} form={form} | {verdict}"


def _verdict(fx: dict, status: str, out: str, variant: Path) -> str:
    if "has no tools" in out:
        return "REFUSED (no tools at this scope)"
    got = _lf(variant.read_bytes()) if variant.is_file() else None
    if status == "deep-proposed":
        if got is None:
            return "NO VARIANT" + (" (nothing to change)" if "nothing to change" in out else "")
        return "MATCH" if got == _lf(fx["expected"]) else "DIFFERS"
    if status == "deep-empty":
        return "MATCH" if got is None and "nothing to change" in out else "CHANGED (expected no change)"
    if status == "deep-failed":
        return "MATCH" if f"NOT KEPT" in out and got is None else "KEPT (expected a refusal beyond the scope)"
    return "UNKNOWN"


LIVE_CASES = [(n, s, st) for n, fx in ALL.items() for s, st in fx["scopes"].items()]


@pytest.mark.skipif(not os.environ.get("CCS_GOLDEN_AI"),
                    reason="set CCS_GOLDEN_AI=<preset> to ask a real backend")
@pytest.mark.parametrize("live_case", LIVE_CASES, ids=[f"{n}@{s}" for n, s, _ in LIVE_CASES])
def test_live(tmp_path, capsys, live_case):
    """A real backend at each scope the fixture lists. Prints one matrix line
    per case; the form is read off the report (the no-tools guarantees line
    says so). A miss is a finding the person judges, so the line is the
    record and only a crash fails the test."""
    name, scope, status = live_case
    fx = ALL[name]
    preset = os.environ["CCS_GOLDEN_AI"]
    w = _world(tmp_path, fx)
    rc = _run(w, preset, scope)
    out = capsys.readouterr().out
    assert rc in (EXIT_CLEAN, EXIT_DRIFT), out
    form = "no-tools" if "no tools" in out else "tools"
    verdict = _verdict(fx, status, out, airecord.proposal_path(w["merged"], 1))
    line = _line(preset, os.environ.get("CCS_GOLDEN_MODEL", ""), name, scope, form, verdict)
    assert LINE_SHAPE.match(line), line
    print(line)
    results = os.environ.get("CCS_GOLDEN_RESULTS")
    if results:
        with open(results, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    with capsys.disabled():
        print(line)


def test_the_matrix_line_names_scope_and_form_as_separate_words():
    """N2 of the latitude design: the line's shape is pinned so a freedom
    word can be added beside scope and form without a reformat."""
    line = _line("lmstudio", "", "bc-python-broken", "hunk", "no-tools", "MATCH")
    assert line == "GOLDEN-DEEP | lmstudio | bc-python-broken | scope=hunk form=no-tools | MATCH"
    assert LINE_SHAPE.match(line)
    with_model = _line("openrouter", "google/gemini-2.5-flash", "rung-4-far-file", "project", "tools", "DIFFERS")
    assert LINE_SHAPE.match(with_model) and "| scope=project form=tools |" in with_model
    assert not LINE_SHAPE.match("GOLDEN-DEEP | lmstudio | bc-python-broken | hunk | MATCH")


# -- the fixtures' own coherence -------------------------------------------------------------------

def test_every_fixture_merges_clean_and_its_mechanical_text_is_gits(tmp_path):
    """The premise of the set: every fixture is two diff-hunks and no
    conflict-hunk, so git merges it without markers and its stored
    mechanical text is what git produces -- through the same call the
    command makes."""
    for name, fx in ALL.items():
        lines, rc = basefind.merge_file_diff3(basefind.lines_of(fx["ours"]), basefind.lines_of(fx["base"]),
                                              basefind.lines_of(fx["theirs"]), tmp_path)
        assert rc == 0, f"{name}: git merge-file reports {rc} conflict-hunk(s); the deep golden set is diff-hunks only"
        got = _lf("\n".join(lines).encode("utf-8")).rstrip(b"\n")
        assert got == _lf(fx["mechanical"]).rstrip(b"\n"), f"{name}: the stored mechanical text is not git's"


def test_every_fixture_names_its_cell_and_its_rung():
    for name, fx in ALL.items():
        assert fx.get("cells"), name
        assert fx["needed"] == "none" or fx["needed"] in airung.RUNGS, name
        for scope in fx["scopes"]:
            assert scope in airung.RUNGS, (name, scope)
        if fx["expected"] is None:
            assert fx["writes"] == {} and set(fx["scopes"].values()) == {"deep-empty"}, name
