"""The golden set for `ccs merge --ai`: conflicts with known-right answers.

The north star (2026-09-05): `ccs merge --ai` completes a real three-way
merge through each of claude, codex, lmstudio and openrouter, with results
the maintainer judges reasonable or that MATCH A GOLDEN SET. This is that
set. Each fixture is three sides, an optional rules file, a canned answer
in the model's own vocabulary (line ids), and the EXPECTED MERGED TEXT --
not the expected ids, because two id selections can assemble the same file
and the file is what a person judges. Comparison is LF-normalised bytes.

Two modes over the same fixtures:

  canned -- always runs. `--ai-response` carries the fixture's answer, so
            the pipeline from answer to proposal is proven before any model
            is asked. Green here means the fixture is coherent.
  live   -- runs only when CCS_GOLDEN_AI names a preset (claude, codex,
            lmstudio, openrouter, ...). The backend is asked for real, its
            proposal is compared to the same expected text, and one matrix
            line per fixture is printed for the witnessed runs' record. A
            miss is a finding, not a defect: it says what THIS model did with
            THIS shape of conflict.

The fixtures are drawn from the condition-space table of 2026-09-04
(`2026-09-04__21-30-00__set__ccs-merge-ai-condition-space.md`): the one
cell with live evidence, the six unknowns, and the negative case whose right
answer cannot be selected. Real-content fixtures, if wanted, go under
tests/golden/ai-merge/<name>/ as files (base.md, ours.md, theirs.md,
answer.json, expected.merged, optional rules.md) and are picked up here too;
private ones live outside the repo.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from dazzle_claude_config import airecord
from dazzle_claude_config.cli import EXIT_CLEAN, EXIT_DRIFT, main

from test_merge_ai import GOOD, LIVE, V1, V2, _ccs, _world

GOLDEN_DIR = Path(__file__).resolve().parent / "golden" / "ai-merge"


def _lf(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


# -- the fixtures ----------------------------------------------------------------
#
# base / ours / theirs are the three sides of skills/s.md; `answer` is the
# canned response (line ids: O = ours, T = theirs, B = base, numbered within
# the hunk); `expected` is the merged text; `report` lists substrings the
# merge report must print; `rules` is a rules file (paragraphs become R1..),
# installed as _default.md unless `per_file` is set.

#: Which side wins a symmetric rewrite is policy, not merging. Every fixture
#: whose expected text depends on that policy states it, so the golden judges
#: an answer against a rule the model was shown rather than against a coin.
PREFER_PAYLOAD = ("TAKE the payload's wording when both sides rewrote the same line; "
                  "the box's local rewording of an upstream line is discarded.\n")

FIXTURES: dict[str, dict] = {
    "one-side-whole-similar": dict(
        cells="B: one side whole, similarity at or above the ratio -- the one cell with live evidence",
        base=V1, ours=LIVE, theirs=V2,
        # The first live run of the golden set (claude, 2026-09-05) taught the
        # set something: with no rule, which side wins a symmetric rewrite is
        # POLICY, and the model reasoned it from the dossier ("the live edit
        # is uncommitted and therefore newer") -- consistently, on every
        # fixture of this shape, choosing ours. A golden with no stated
        # preference was judging a coin. The rule states it.
        rules=PREFER_PAYLOAD,
        answer=GOOD, expected=V2),

    "one-side-whole-dissimilar-under-a-rule": dict(
        cells="B: one side whole, similarity below the ratio -- the dropped line needs a cited rule",
        base=b"# skill\nalpha\nrule B\n",
        ours=b"# skill\nbeta beta beta beta beta\nrule B\n",
        theirs=b"# skill\ngamma gamma gamma gamma gamma gamma\nrule B\n",
        rules="TAKE the payload's wording everywhere; local rewordings of upstream lines are discarded.\n",
        answer={"hunks": [{"hunk": 1, "lines": ["T1"], "rules": ["R1"], "rationale": "R1: take upstream"}]},
        expected=b"# skill\ngamma gamma gamma gamma gamma gamma\nrule B\n",
        report=["dropped under R1"]),

    "interleaving": dict(
        cells="B: an interleaving -- both sides added DIFFERENT lines where the base had nothing (kind: additions); live since 2026-09-05",
        # The first version added "A added here" against "B added here" --
        # 92% similar by the tool's own ratio, so a side-pick by its own rules,
        # and Opus 5 duly picked a side. A real interleaving adds different
        # things; this one now does, and the hunk classifies as `additions`.
        base=b"x\ny\n",
        ours=b"x\nSet the timeout to 30 seconds.\ny\n",
        theirs=b"x\nLog every retry.\ny\n",
        answer={"hunks": [{"hunk": 1, "lines": ["O1", "T1"], "rules": [], "rationale": "keep both additions"}]},
        # either order is right; `expected` may be a tuple of acceptable texts
        expected=(b"x\nSet the timeout to 30 seconds.\nLog every retry.\ny\n",
                  b"x\nLog every retry.\nSet the timeout to 30 seconds.\ny\n")),

    "whole-region-drop-under-a-rule": dict(
        cells="B: a drop of a whole region, licensed by a rule",
        base=b"k\nnote: old\nz\n", ours=b"k\nnote: mine\nz\n", theirs=b"k\nnote: theirs\nz\n",
        rules="DROP any `note:` line entirely; notes are scratch, not configuration.\n",
        answer={"hunks": [{"hunk": 1, "lines": [], "rules": ["R1"], "rationale": "R1: notes go"}]},
        expected=b"k\nz\n",
        report=["dropped under R1"]),

    "rewrite-hunk-under-a-rule": dict(
        cells="D2: a rewrite-kind hunk (one side rewrote several lines); unknown live",
        base=b"a\nb\nc\nd\n", ours=b"a\nB one\nB two\nd\n", theirs=b"a\nb\nc changed\nd\n",
        rules="TAKE a local rewrite of a block whole; the payload's line edits inside it are discarded.\n",
        answer={"hunks": [{"hunk": 1, "lines": ["O1", "O2"], "rules": ["R1"], "rationale": "R1: local rewrite"}]},
        expected=b"a\nB one\nB two\nd\n"),

    "multi-hunk": dict(
        cells="D3: many hunks in one file, each answered; unknown live until 2026-09-05",
        base=b"a\nkeep\nc\n", ours=b"a1\nkeep\nc1\n", theirs=b"a2\nkeep\nc2\n",
        # An earlier version expected ours on hunk 1 and theirs on hunk 2 with
        # no rule saying so -- an arbitrary mix no model could be expected to
        # guess. The cell is "many hunks", not "different answers per hunk".
        rules=PREFER_PAYLOAD,
        answer={"hunks": [{"hunk": 1, "lines": ["T1"], "rules": ["R1"], "rationale": "R1"},
                          {"hunk": 2, "lines": ["T1"], "rules": ["R1"], "rationale": "R1"}]},
        expected=b"a2\nkeep\nc2\n"),

    "per-file-rules": dict(
        cells="C: a per-file <label>.rules.md rather than _default.md; unknown live",
        base=b"# skill\nalpha\nrule B\n",
        ours=b"# skill\nbeta beta beta beta beta\nrule B\n",
        theirs=b"# skill\ngamma gamma gamma gamma gamma gamma\nrule B\n",
        rules="TAKE the payload's wording everywhere.\n", per_file=True,
        answer={"hunks": [{"hunk": 1, "lines": ["T1"], "rules": ["R1"], "rationale": "R1"}]},
        expected=b"# skill\ngamma gamma gamma gamma gamma gamma\nrule B\n",
        report=["skills__s.md.rules.md"]),

    "supplied-base": dict(
        cells="A: a base supplied with --base-file, with --ai; unknown live until 2026-09-05",
        base=V1, ours=LIVE, theirs=V2, base_file=True,
        rules=PREFER_PAYLOAD,
        answer=GOOD, expected=V2),

    "blend-is-the-right-answer": dict(
        cells="B: a blend -- the right answer is inexpressible by line selection; either side is acceptable and the report must name the words",
        base=V1, ours=LIVE, theirs=V2,
        answer=GOOD,
        report=["both sides rewrote the same paragraph", "upstream", "locally"]),
}


def _dir_fixtures() -> dict[str, dict]:
    """Hand-added fixtures as files under tests/golden/ai-merge/<name>/."""
    out: dict[str, dict] = {}
    if not GOLDEN_DIR.is_dir():
        return out
    for d in sorted(p for p in GOLDEN_DIR.iterdir() if p.is_dir()):
        need = [d / "base.md", d / "ours.md", d / "theirs.md", d / "answer.json"]
        if not all(p.is_file() for p in need):
            continue
        fx = dict(cells=f"from {d.name}/", base=need[0].read_bytes(), ours=need[1].read_bytes(),
                  theirs=need[2].read_bytes(), answer=json.loads(need[3].read_text(encoding="utf-8")))
        if (d / "expected.merged").is_file():
            fx["expected"] = (d / "expected.merged").read_bytes()
        if (d / "expected.report").is_file():
            fx["report"] = [l for l in (d / "expected.report").read_text(encoding="utf-8").splitlines() if l.strip()]
        if (d / "rules.md").is_file():
            fx["rules"] = (d / "rules.md").read_text(encoding="utf-8")
        out[f"dir:{d.name}"] = fx
    return out


ALL = {**FIXTURES, **_dir_fixtures()}


@pytest.fixture(params=sorted(ALL))
def fixture(request):
    return request.param, ALL[request.param]


# -- the runner -----------------------------------------------------------------

def _build(tmp_path: Path, fx: dict) -> dict:
    history = (fx["theirs"],) if fx.get("base_file") else (fx["base"], fx["theirs"])
    w = _world(tmp_path, history=history, live=fx["ours"])
    if fx.get("rules"):
        d = w["user"] / "ccs-merge-rules"
        d.mkdir(parents=True, exist_ok=True)
        name = "skills__s.md.rules.md" if fx.get("per_file") else "_default.md"
        (d / name).write_text(fx["rules"], encoding="utf-8")
    # CCS_GOLDEN_MODEL overrides the preset's model for an A/B run (it lands
    # in the world's config as ai_merge_model, exactly as a person would set it)
    model = os.environ.get("CCS_GOLDEN_MODEL")
    if model:
        (w["user"] / "ccs-config.json").write_text(json.dumps({"ai_merge_model": model}), encoding="utf-8")
    return w


def _args(tmp_path: Path, fx: dict, *ai: str) -> list[str]:
    args = ["merge", "skills/s.md", "--ai", *ai, "--no-launch"]
    if fx.get("base_file"):
        bf = tmp_path / "supplied-base.md"
        bf.write_bytes(fx["base"])
        args += ["--base-file", str(bf)]
    return args


def _accepted(fx: dict) -> list[bytes]:
    """The golden text(s): one, or a tuple when more than one order is right."""
    e = fx["expected"]
    return [_lf(e)] if isinstance(e, bytes) else [_lf(x) for x in e]


def _check(w: dict, fx: dict, out: str) -> None:
    if "expected" in fx:
        prop = airecord.proposal_path(w["merged"])
        assert prop.is_file(), f"no proposal was staged:\n{out}"
        got = _lf(prop.read_bytes())
        assert got in _accepted(fx), (
            f"proposal differs from the golden text:\n--- got ---\n{got.decode('utf-8', 'replace')}"
            f"\n--- expected (any of {len(_accepted(fx))}) ---\n"
            f"{_accepted(fx)[0].decode('utf-8', 'replace')}\n--- report ---\n{out}")
    for s in fx.get("report", []):
        assert s in out, f"report lacks {s!r}:\n{out}"


def test_canned(tmp_path, capsys, fixture):
    """The fixture is coherent: its own answer assembles to its own expected text."""
    name, fx = fixture
    w = _build(tmp_path, fx)
    answer = tmp_path / "answer.json"
    answer.write_text(json.dumps(fx["answer"]), encoding="utf-8")
    rc = main(_ccs(w, *_args(tmp_path, fx, "--ai-response", str(answer))))
    out = capsys.readouterr().out
    assert rc in (EXIT_CLEAN, EXIT_DRIFT), out
    _check(w, fx, out)


@pytest.mark.skipif(not os.environ.get("CCS_GOLDEN_AI"),
                    reason="set CCS_GOLDEN_AI=<preset> to ask a real backend")
def test_live(tmp_path, capsys, fixture):
    """A real backend, judged against the same golden text. Prints one matrix
    line per fixture; a miss is a finding about this model and this shape."""
    name, fx = fixture
    preset = os.environ["CCS_GOLDEN_AI"]
    w = _build(tmp_path, fx)
    rc = main(_ccs(w, *_args(tmp_path, fx, preset, "--ai-refresh")))
    out = capsys.readouterr().out
    prop = airecord.proposal_path(w["merged"])
    got = _lf(prop.read_bytes()) if prop.is_file() else None
    if got is None:
        verdict = "NO PROPOSAL"
    elif "expected" not in fx:                       # a report-only fixture: either side is acceptable
        verdict = "REPORT " + ("OK" if all(s in out for s in fx.get("report", [])) else "LACKING")
    else:
        verdict = "MATCH" if got in _accepted(fx) else "DIFFERS"
    model = os.environ.get("CCS_GOLDEN_MODEL", "")
    line = f"GOLDEN | {preset}{(' ' + model) if model else ''} | {name} | {verdict}"
    print(line)
    results = os.environ.get("CCS_GOLDEN_RESULTS")
    if results:
        with open(results, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    with capsys.disabled():
        print(line)
    _check(w, fx, out)


def test_the_stale_record_cell(tmp_path, capsys):
    """G: a record whose sides have moved since the proposal -- two steps:
    a canned proposal, then the live side edited, then the report reads the
    record and says which side changed."""
    fx = FIXTURES["one-side-whole-similar"]
    w = _build(tmp_path, fx)
    answer = tmp_path / "answer.json"
    answer.write_text(json.dumps(fx["answer"]), encoding="utf-8")
    main(_ccs(w, *_args(tmp_path, fx, "--ai-response", str(answer))))
    capsys.readouterr()
    w["live_file"].write_bytes(b"# skill\nrule A locally revised AGAIN\nrule B\n")
    main(_ccs(w, "merge", "skills/s.md", "--ai", "prompt-only", "--no-launch"))
    out = capsys.readouterr().out
    assert "has changed since" in out, out


def test_every_fixture_names_its_cell():
    for name, fx in ALL.items():
        assert fx.get("cells"), name
