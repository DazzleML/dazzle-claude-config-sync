"""U5 of the deep merge (#64): the plan and the report -- `--ai claude,deep`
wired into `ccs merge`, with #62 and #63 folded in.

    --ai <step>[,<step>...]   `claude,deep` = the recipe first, its result to
                              the deep step; `deep` alone runs on the
                              configured backend and inserts the recipe
                              before it; `deep:<preset>` names one
    --ai-scope hunk|file|neighbours|project   the rung the deep step may
                              reach (default hunk)

No automatic winner: the report shows every answer with its own
guarantees line (C7), the record holds them all with `chosen` unmoved
(C6), and `--accept` asks with the guarantees of whichever answer the
person put in `.merged`. Written BEFORE the change (red by construction)
over `test_merge_ai`'s world and a fake `cli` transport that answers the
recipe's prompt with a line selection and the deep step's prompt by
editing the sandbox.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dazzle_claude_config import airecord, merge
from dazzle_claude_config.cli import EXIT_CLEAN, EXIT_DRIFT, EXIT_ERROR, main

from test_merge_ai import GOOD, LIVE, PROPOSAL, V2, _ccs, _world

DEEP_JSON = json.dumps({"summary": "added the closing rule the two sides implied",
                        "edits": [{"path": "s.md", "region": "skill", "reason": "both sides left rule C implicit"}]})
DEEP_EDIT = V2 + b"rule C\n"          # an insertion inside the one region (the whole file is under `# skill`)


#: The no-tools form's answer: a unified diff against the recipe's proposal
#: (V2, three lines) adding the same closing rule the tools form writes.
DEEP_DIFF = ("--- a/s.md\n+++ b/s.md\n@@ -1,3 +1,4 @@\n"
             " # skill\n rule A revised upstream\n rule B\n+rule C\n")


class _Fake:
    """A fake `cli` transport that tells the two prompts apart: the
    recipe's (`resolve the dual-touched hunks`) gets a line selection; the
    deep step's (`the deep step`) edits the sandbox as scripted."""
    deep_writes: bytes | None = DEEP_EDIT          # None: the deep step changes nothing
    escape_to: Path | None = None                  # an ABSOLUTE real path to write outside the sandbox
    summary: str = "added the closing rule the two sides implied"
    warning: str = ""
    calls: list[str] = []
    prompts: dict[str, str] = {}
    models: list[str] = []                         # the spec's model per call, in order

    def probe(self, spec):
        from dazzle_claude_config._vendor.ailib.types import Readiness
        return Readiness(True, "its CLI was found: C:/fake/claude.exe", warning=_Fake.warning)

    def capabilities(self, spec):
        return frozenset({"model", "stream", "tools"})

    def _json(self):
        return json.dumps({"summary": _Fake.summary,
                           "edits": [{"path": "s.md", "region": "skill",
                                      "reason": "both sides left rule C implicit"}]})

    def invoke(self, spec, req):
        from dazzle_claude_config._vendor.ailib.types import Response
        if "the deep step" in req.prompt.splitlines()[0]:
            _Fake.calls.append("deep")
            _Fake.prompts["deep"] = req.prompt
            assert req.workdir, "the deep step runs in the sandbox"
            if _Fake.deep_writes is not None:
                target = Path(req.workdir) / "checkout" / "dotclaude" / "skills" / "s.md"
                target.write_bytes(_Fake.deep_writes)
            if _Fake.escape_to is not None:
                _Fake.escape_to.write_text("the model reached outside\n", encoding="utf-8")
            return Response("answered", text="Done.\n```json\n" + self._json() + "\n```\n",
                            model_used="fake-opus", honoured=("model", "tools"))
        _Fake.calls.append("recipe")
        _Fake.prompts["recipe"] = req.prompt
        assert not req.workdir, "the recipe never names a workdir"
        return Response("answered", text="```json\n" + json.dumps(GOOD) + "\n```\n",
                        model_used="fake-opus", honoured=("model",))


class _NoTools:
    """A fake `openai_compat` transport: the same two prompts, no tools --
    the recipe answers with line ids, the deep step with a diff."""
    diff: str = DEEP_DIFF
    calls: list[str] = []

    def probe(self, spec):
        from dazzle_claude_config._vendor.ailib.types import Readiness
        return Readiness(True, "http://fake/v1 -- reachable, model fake-27b", warning="")

    def capabilities(self, spec):
        return frozenset({"model", "schema"})

    def invoke(self, spec, req):
        from dazzle_claude_config._vendor.ailib.types import Response
        assert not req.workdir, "a no-tools backend is never given a workdir"
        if "the deep step" in req.prompt.splitlines()[0]:
            _NoTools.calls.append("deep")
            return Response("answered", text="```diff\n" + _NoTools.diff + "```\n\n```json\n"
                                             + json.dumps({"summary": "added the closing rule",
                                                           "edits": [{"path": "s.md", "region": "skill",
                                                                      "reason": "implied by both"}]}) + "\n```\n",
                            model_used="fake-27b", honoured=("model",))
        _NoTools.calls.append("recipe")
        return Response("answered", text="```json\n" + json.dumps(GOOD) + "\n```\n",
                        model_used="fake-27b", honoured=("model", "schema"))


@pytest.fixture
def fake_cli(monkeypatch):
    from dazzle_claude_config._vendor.ailib import backend as _bm
    _bm.transport_for("cli")
    monkeypatch.setitem(_bm._TRANSPORTS, "cli", _Fake())
    monkeypatch.setitem(_bm._TRANSPORTS, "openai_compat", _NoTools())
    _Fake.deep_writes, _Fake.warning, _Fake.calls = DEEP_EDIT, "", []
    _Fake.escape_to, _Fake.prompts, _Fake.models = None, {}, []
    _Fake.summary = "added the closing rule the two sides implied"
    _NoTools.diff, _NoTools.calls = DEEP_DIFF, []
    monkeypatch.delenv("CCS_AI_MERGE_BACKEND", raising=False)


def _configured(w, backend):
    (w["user"] / "ccs-config.json").write_text(json.dumps({"ai_merge_backend": backend}), encoding="utf-8")


# -- the grammar ---------------------------------------------------------------------

def _plan(token, configured="claude"):
    from dazzle_claude_config.cli import parse_plan
    return [(s.kind, s.backend) for s in parse_plan(token, configured=configured)]


def test_parse_plan_the_recipe_alone_and_the_configured_default():
    assert _plan("auto", configured="lmstudio") == [("recipe", "lmstudio")]
    assert _plan("auto", configured="prompt-only") == [("recipe", "prompt-only")]
    assert _plan("claude") == [("recipe", "claude")]
    assert _plan("prompt-only") == [("recipe", "prompt-only")]


def test_parse_plan_claude_then_deep_is_the_recipe_first_then_the_deep_step_on_the_same_backend():
    """The maintainer's reading, confirmed at the design gate: "claude" is
    the initial layer, its result goes to "deep"."""
    assert _plan("claude,deep") == [("recipe", "claude"), ("deep", "claude")]
    assert _plan("claude,deep:lmstudio") == [("recipe", "claude"), ("deep", "lmstudio")]


def test_parse_plan_a_deep_with_no_recipe_before_it_inserts_one():
    assert _plan("deep", configured="claude") == [("recipe", "claude"), ("deep", "claude")]
    assert _plan("deep:lmstudio", configured="claude") == [("recipe", "lmstudio"), ("deep", "lmstudio")]


def test_parse_plan_refusals_say_why():
    with pytest.raises(ValueError, match="deep needs a backend"):
        _plan("deep", configured="prompt-only")
    with pytest.raises(ValueError, match="one recipe step per plan"):
        _plan("claude,codex")
    with pytest.raises(ValueError, match="gpt9"):
        _plan("gpt9")
    with pytest.raises(ValueError, match="gpt9"):
        _plan("claude,deep:gpt9")
    with pytest.raises(ValueError, match="empty step"):        # by name, not as an unknown backend (v0.6.7 sweep, M2)
        _plan("claude,,deep")


def test_the_scope_flag_takes_the_ladders_tokens_only(tmp_path, capsys):
    w = _world(tmp_path)
    with pytest.raises(SystemExit):
        main(_ccs(w, "merge", "skills/s.md", "--ai", "claude,deep", "--ai-scope", "everything", "--no-launch"))
    err = capsys.readouterr().err
    assert "hunk" in err and "file" in err and "neighbours" in err and "project" in err


# -- C6: two answers, one record, no winner ------------------------------------------------

def test_c6_claude_then_deep_yields_two_answers_and_a_numbered_variant(tmp_path, capsys, fake_cli):
    w = _world(tmp_path)
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "claude,deep", "--no-launch"))
    out = capsys.readouterr().out
    assert rc == EXIT_CLEAN, out
    assert _Fake.calls == ["recipe", "deep"]
    assert "steps: claude (recipe), deep via claude" in out          # the plan line, before the first call
    rec = airecord.load(airecord.record_path(w["merged"]))
    assert [airecord.answer_kind(a) for a in rec.answers] == ["recipe", "deep"] and rec.chosen == 0
    assert airecord.proposal_path(w["merged"]).read_bytes() == PROPOSAL
    assert airecord.proposal_path(w["merged"], 1).read_bytes() == DEEP_EDIT
    assert w["merged"].read_bytes() == PROPOSAL                     # the copy rule: the recipe's, never the deep variant
    assert w["live_file"].read_bytes() == LIVE                      # nothing installed
    assert "staged skills/s.md" in out and ".merged-ai.1" in out
    assert "(deep via claude" in out


def test_c7_the_report_prints_two_guarantees_lines_that_differ(tmp_path, capsys, fake_cli):
    w = _world(tmp_path)
    main(_ccs(w, "merge", "skills/s.md", "--ai", "claude,deep", "--no-launch"))
    out = capsys.readouterr().out
    lines = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("guarantees:")]
    assert len(lines) == 2 and lines[0] != lines[1]
    assert "every line came from one of the three sides" in lines[0] and "never sent" in lines[0]
    assert "may contain text no side wrote" in lines[1] and "the ladder allowed edits in" in lines[1]
    assert "needed: hunk" in lines[1]


def test_the_deep_report_names_the_edits_with_reasons_and_the_touched_count(tmp_path, capsys, fake_cli):
    w = _world(tmp_path)
    main(_ccs(w, "merge", "skills/s.md", "--ai", "claude,deep", "--no-launch"))
    out = capsys.readouterr().out
    assert "both sides left rule C implicit" in out
    assert "files touched: 1" in out
    assert "the closing rule the two sides implied" in out


# -- deep alone, and refusals ------------------------------------------------------------

def test_deep_alone_inserts_the_recipe_on_the_configured_backend(tmp_path, capsys, fake_cli):
    w = _world(tmp_path)
    _configured(w, "claude")
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "deep", "--no-launch"))
    out = capsys.readouterr().out
    assert rc == EXIT_CLEAN, out
    assert _Fake.calls == ["recipe", "deep"]
    assert "steps: claude (recipe), deep via claude" in out


def test_deep_on_prompt_only_is_refused_before_anything_runs(tmp_path, capsys, fake_cli):
    w = _world(tmp_path)
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "deep", "--no-launch"))
    out = capsys.readouterr().out
    assert rc == EXIT_ERROR
    assert "deep needs a backend" in out and "deep:<preset>" in out and "ai_merge_backend" in out
    assert _Fake.calls == []


def test_a_deep_step_that_reaches_beyond_the_scope_is_pending_and_keeps_no_variant(tmp_path, capsys, fake_cli):
    """The edit lands in the one region (rung 1) so a narrower scope cannot
    be built from this world; instead the fake edits a NEIGHBOUR, which is
    rung 3, and the scope stays at hunk."""
    w = _world(tmp_path)
    other = w["co"] / "dotclaude" / "skills" / "other.md"
    other.write_text("a neighbour\n", encoding="utf-8")
    import subprocess as sp
    from conftest import GIT_ID
    sp.run(["git", *GIT_ID, "-C", str(w["co"]), "add", "-A"], check=True, capture_output=True)
    sp.run(["git", *GIT_ID, "-C", str(w["co"]), "commit", "-qm", "a neighbour"], check=True, capture_output=True)

    class _Wide(_Fake):
        def invoke(self, spec, req):
            if "the deep step" in req.prompt.splitlines()[0]:
                (Path(req.workdir) / "checkout" / "dotclaude" / "skills" / "other.md").write_text("edited\n", encoding="utf-8")
            return super().invoke(spec, req)
    from dazzle_claude_config._vendor.ailib import backend as _bm
    _bm._TRANSPORTS["cli"] = _Wide()
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "claude,deep", "--no-launch"))
    out = capsys.readouterr().out
    assert rc == EXIT_DRIFT, out                                    # pending work: the person decides
    assert "NOT KEPT skills/s.md" in out and "needed neighbours" in out and "hunk was allowed" in out
    assert "other.md" in out                                        # the edit it would have made
    assert not airecord.proposal_path(w["merged"], 1).exists()


def test_a_deep_step_that_changes_nothing_says_so_and_is_not_pending(tmp_path, capsys, fake_cli):
    w = _world(tmp_path)
    _Fake.deep_writes = None
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "claude,deep", "--no-launch"))
    out = capsys.readouterr().out
    assert rc == EXIT_CLEAN
    assert "nothing to change" in out and "(deep via claude)" in out
    rec = airecord.load(airecord.record_path(w["merged"]))
    assert len(rec.answers) == 1                                    # no answer recorded for an empty change


def test_the_scope_flag_reaches_the_deep_step(tmp_path, capsys, fake_cli):
    w = _world(tmp_path)
    main(_ccs(w, "merge", "skills/s.md", "--ai", "claude,deep", "--ai-scope", "file", "--no-launch"))
    out = capsys.readouterr().out
    assert "this file only" in out                                  # the guarantees line's scope phrase
    rec = airecord.load(airecord.record_path(w["merged"]))
    assert rec.answers[1]["scope"] == {"allowed": 2, "needed": 1}


# -- the accept question and the diff -----------------------------------------------------

def test_accept_on_the_deep_variant_asks_with_its_guarantees_and_moves_chosen_only_on_yes(tmp_path, capsys, fake_cli, monkeypatch):
    w = _world(tmp_path)
    main(_ccs(w, "merge", "skills/s.md", "--ai", "claude,deep", "--no-launch"))
    capsys.readouterr()
    w["merged"].write_bytes(DEEP_EDIT)                              # the person puts the deep variant in .merged
    seen = []
    monkeypatch.setattr(merge, "_ask_ai_on_console",
                        lambda item, rec: seen.append((rec.chosen, rec.answer.get("guarantees", ""))) or False)
    rc = main(_ccs(w, "merge", "skills/s.md", "--accept", "--no-launch"))
    assert rc == EXIT_DRIFT
    assert seen and seen[0][0] == 1 and "may contain text no side wrote" in seen[0][1]
    rec = airecord.load(airecord.record_path(w["merged"]))
    assert rec.chosen == 0 and not rec.accepted_unchanged            # a no moves nothing
    monkeypatch.setattr(merge, "_ask_ai_on_console", lambda item, rec: True)
    rc = main(_ccs(w, "merge", "skills/s.md", "--accept", "--no-launch"))
    assert rc == EXIT_CLEAN
    rec = airecord.load(airecord.record_path(w["merged"]))
    assert rec.chosen == 1 and rec.accepted_unchanged
    assert w["live_file"].read_bytes() == DEEP_EDIT


def test_diff_ai_variant_opens_the_numbered_variant(tmp_path, capsys, fake_cli, monkeypatch):
    w = _world(tmp_path)
    main(_ccs(w, "merge", "skills/s.md", "--ai", "claude,deep", "--no-launch"))
    capsys.readouterr()
    opened = []
    monkeypatch.setattr(merge, "resolve_difftool", lambda tool: "fake-tool")
    monkeypatch.setattr(merge, "launch_difftool", lambda name, a, b: opened.append((name, Path(a), Path(b))))
    rc = main(_ccs(w, "diff", "skills/s.md", "--ai", "--variant", "1"))
    assert rc == EXIT_CLEAN
    assert opened and opened[0][1] == airecord.proposal_path(w["merged"], 1)
    rc = main(_ccs(w, "diff", "skills/s.md", "--ai", "--variant", "7"))
    out = capsys.readouterr().out
    assert "no AI answer 7" in out


# -- #62: the readiness warning in the report ---------------------------------------------

def test_62_a_backend_warning_is_one_line_in_the_report_and_absent_without(tmp_path, capsys, fake_cli):
    w = _world(tmp_path)
    _Fake.warning = "loaded with a 197,120-token context"
    main(_ccs(w, "merge", "skills/s.md", "--ai", "claude,deep", "--no-launch"))
    out = capsys.readouterr().out
    assert out.count("backend: loaded with a 197,120-token context") == 2      # the recipe's line and the deep step's
    _Fake.warning = ""
    main(_ccs(w, "merge", "skills/s.md", "--ai", "claude", "--ai-refresh", "--no-launch"))
    assert "backend:" not in capsys.readouterr().out


def test_62_the_warning_is_printed_beside_a_backend_failure_too(tmp_path, capsys, monkeypatch):
    """#62's third criterion: a timeout is usually the warning's prediction
    coming true, so a failed backend's warning stands beside the failure."""
    from dazzle_claude_config._vendor.ailib import backend as _bm
    from dazzle_claude_config._vendor.ailib.types import Readiness

    class _Down(_Fake):
        def probe(self, spec):
            return Readiness(False, "codex is not on PATH", warning="loaded with a 197,120-token context")
    _bm.transport_for("cli")
    monkeypatch.setitem(_bm._TRANSPORTS, "cli", _Down())
    w = _world(tmp_path)
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "codex", "--no-launch"))
    out = capsys.readouterr().out
    assert rc == EXIT_DRIFT
    assert "ai failed skills/s.md" in out and "backend: loaded with a 197,120-token context" in out


# -- v0.6.5 mutation sweep (survivor kills) ------------------------------------------------

def test_a_config_that_spells_the_backend_out_as_null_reads_as_prompt_only_M4(tmp_path, capsys, fake_cli):
    """v0.6.5 sweep, survivor M4: `cfg.get(k) or PROMPT_ONLY`, not
    `cfg.get(k, PROMPT_ONLY)` -- a config file with the key present and null
    means unset, and the bare flag must reach the floor rather than build a
    backend called None."""
    w = _world(tmp_path)
    (w["user"] / "ccs-config.json").write_text(json.dumps({"ai_merge_backend": None}), encoding="utf-8")
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "--no-launch"))
    out = capsys.readouterr().out
    assert rc == EXIT_DRIFT, out
    assert "prompt written" in out and _Fake.calls == []


def test_each_step_runs_on_its_own_backend_M6(tmp_path, capsys, fake_cli):
    """v0.6.5 sweep, survivor M6: `AiOptions.backend` is the FIRST step's,
    and `ai_step` reads the options -- so a plan whose steps differ ran the
    recipe on the wrong backend. `claude,deep:lmstudio` is the recipe on
    claude and the deep step on lmstudio, and the report says both."""
    w = _world(tmp_path)
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "claude,deep:lmstudio", "--no-launch"))
    out = capsys.readouterr().out
    assert rc == EXIT_CLEAN, out
    assert "steps: claude (recipe), deep via lmstudio" in out
    assert _Fake.calls == ["recipe"] and _NoTools.calls == ["deep"]      # one call each, to its own backend
    assert "the AI's proposal (claude)" in out                          # the recipe's own line
    assert "(deep via lmstudio" in out
    rec = airecord.load(airecord.record_path(w["merged"]))
    assert rec.answers[0]["backend"] == "claude" and rec.answers[1]["backend"] == "lmstudio"


def test_a_backend_that_escapes_the_sandbox_is_reported_in_the_merge_report_M7(tmp_path, capsys, fake_cli):
    """v0.6.5 sweep, survivor M7: `deep-escaped` shared the `NOT KEPT`
    branch with `deep-failed` and nothing tested it, so a mutant that
    dropped it printed no line at all for the one outcome that must never
    be silent."""
    w = _world(tmp_path)
    _Fake.escape_to = w["live"] / "skills" / "escaped.md"
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "claude,deep", "--no-launch"))
    out = capsys.readouterr().out
    assert rc == EXIT_DRIFT, out
    assert "NOT KEPT skills/s.md" in out
    assert "changed outside the sandbox" in out and "escaped.md" in out
    assert not airecord.proposal_path(w["merged"], 1).exists()


def test_an_empty_summary_prints_no_blank_line_M8(tmp_path, capsys, fake_cli):
    """v0.6.5 sweep, survivor M8: only the parts that exist are printed."""
    w = _world(tmp_path)
    _Fake.summary = ""
    main(_ccs(w, "merge", "skills/s.md", "--ai", "claude,deep", "--no-launch"))
    out = capsys.readouterr().out
    assert "the AI's answer skills__s.md.merged-ai.1" in out
    assert "\n    \n" not in out and "\n\n" not in out.split("staged skills/s.md")[-1]


def test_the_variant_hint_names_the_answer_number_M9(tmp_path, capsys, fake_cli):
    """v0.6.5 sweep, survivor M9: the hint must be runnable as printed."""
    w = _world(tmp_path)
    main(_ccs(w, "merge", "skills/s.md", "--ai", "claude,deep", "--no-launch"))
    out = capsys.readouterr().out
    assert "ccs diff skills/s.md --ai --variant 1 opens it beside yours" in out


def test_the_question_is_asked_about_the_answer_in_merged_not_the_last_one_chosen_M10(tmp_path, capsys,
                                                                                       fake_cli, monkeypatch):
    """v0.6.5 sweep, survivor M10: after a deep variant has been accepted
    (`chosen` = 1), putting the RECIPE's proposal back in `.merged` must ask
    about answer 0 -- the answer the bytes actually are, never the one
    chosen last time."""
    w = _world(tmp_path)
    main(_ccs(w, "merge", "skills/s.md", "--ai", "claude,deep", "--no-launch"))
    capsys.readouterr()
    # the deep variant was accepted at some earlier point: the record says so
    rec_path = airecord.record_path(w["merged"])
    rec = airecord.load(rec_path)
    rec.chosen, rec.accepted_unchanged = 1, "2026-09-01"
    airecord.write(rec_path, rec)
    assert w["merged"].read_bytes() == PROPOSAL                 # and `.merged` is answer 0 again
    asked = []
    monkeypatch.setattr(merge, "_ask_ai_on_console",
                        lambda item, r: asked.append((r.chosen, r.answer.get("kind"))) or True)
    rc = main(_ccs(w, "merge", "skills/s.md", "--accept", "--no-launch"))
    assert rc == EXIT_CLEAN
    assert asked == [(0, "recipe")], asked                       # asked about the answer that IS there
    assert airecord.load(rec_path).chosen == 0                   # and the record no longer claims the variant
    assert w["live_file"].read_bytes() == PROPOSAL


def test_the_deep_step_reads_the_recipes_proposal_not_gits_conflicted_merge_M11(tmp_path, capsys, fake_cli):
    """v0.6.5 sweep, survivor M11: the deep step is handed the recipe's
    RESULT. Handed git's diff3 merge instead it would read conflict markers
    as content -- the one thing the recipe exists to remove."""
    w = _world(tmp_path)
    main(_ccs(w, "merge", "skills/s.md", "--ai", "claude,deep", "--no-launch"))
    capsys.readouterr()
    prompt = _Fake.prompts["deep"]
    assert "<<<<<<<" not in prompt and ">>>>>>>" not in prompt
    assert "rule A revised upstream" in prompt                   # the recipe's proposal (V2)
    assert "rule A locally revised" not in prompt.split("## The two changes")[0]


def test_a_deep_step_that_cannot_run_leaves_the_file_pending_M12(tmp_path, capsys, fake_cli):
    """v0.6.5 sweep, survivor M12: `deep-skipped` is pending work -- the
    person asked for a pass that did not happen, and the exit code says so."""
    w = _world(tmp_path)
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "lmstudio,deep",
                   "--ai-scope", "neighbours", "--no-launch"))
    out = capsys.readouterr().out
    assert rc == EXIT_DRIFT, out
    assert "ai skipped skills/s.md" in out and "no tools" in out and "rung 2 (file)" in out
    assert _NoTools.calls == ["recipe"]                          # the deep step was never called


def test_a_hand_merge_that_loses_a_line_is_still_refused_M15(tmp_path, capsys, fake_cli):
    """v0.6.5 sweep, survivor M15: the tripwire split applies ONLY to a
    `.merged` that is one of the record's answers. Everything else -- a hand
    merge, an edited copy -- keeps the gate it always had."""
    w = _world(tmp_path)
    main(_ccs(w, "merge", "skills/s.md", "--no-launch"))
    capsys.readouterr()
    w["merged"].write_bytes(b"# skill\nrule B\n")                # both sides' unique lines gone
    rc = main(_ccs(w, "merge", "skills/s.md", "--accept", "--no-launch"))
    out = capsys.readouterr().out
    assert rc == merge.EXIT_VALIDATION, out                      # the alarm the verb exists for
    assert "NOT INSTALLED" in out and "dropped:" in out
    assert w["live_file"].read_bytes() == LIVE                   # nothing installed


def test_c8_the_tripwire_prints_at_accept_and_does_not_refuse(tmp_path, capsys, fake_cli, monkeypatch):
    """C8 (#64): a deep variant may contain text no side wrote -- exactly
    what the invented-content check looks for -- so at `--accept` those
    checks are printed and do not refuse."""
    w = _world(tmp_path)
    main(_ccs(w, "merge", "skills/s.md", "--ai", "claude,deep", "--no-launch"))
    capsys.readouterr()
    w["merged"].write_bytes(DEEP_EDIT)                           # "rule C" appears on no side
    monkeypatch.setattr(merge, "_ask_ai_on_console", lambda item, rec: True)
    rc = main(_ccs(w, "merge", "skills/s.md", "--accept", "--no-launch"))
    out = capsys.readouterr().out
    assert rc == EXIT_CLEAN, out
    assert "tripwire skills/s.md" in out and "may contain text no side wrote" in out
    assert "appear in neither side nor the base" in out
    assert w["live_file"].read_bytes() == DEEP_EDIT               # printed, not refused


def test_a_clean_merge_still_gets_the_deep_step_over_gits_own_result_M17(tmp_path, capsys, fake_cli):
    """v0.6.5 sweep, survivor M17: the case the whole feature exists for --
    two sides changed DIFFERENT lines, git merged them cleanly, the recipe
    has no hunks to decide, and the deep step reads git's own result for
    meaning. Skipping it there would skip the b()/c() case by construction."""
    # far apart, so git's own merge is clean and the recipe has no hunk: ours
    # changes the second line, theirs the last
    base = b"# skill\nintro\n\nrule A\nrule B\nrule C\n\nnotes\n"
    ours = b"# skill\nintro, expanded locally\n\nrule A\nrule B\nrule C\n\nnotes\n"
    theirs = b"# skill\nintro\n\nrule A\nrule B\nrule C\n\nnotes, revised upstream\n"
    clean = b"# skill\nintro, expanded locally\n\nrule A\nrule B\nrule C\n\nnotes, revised upstream\n"
    w = _world(tmp_path, history=(base, theirs), live=ours)
    _Fake.deep_writes = clean.replace(b"rule C\n", b"rule C\nrule D\n")
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "claude,deep", "--no-launch"))
    out = capsys.readouterr().out
    assert rc == EXIT_CLEAN, out
    assert "no conflict-hunk" in out                             # the recipe had nothing to decide (U7's wording)
    assert _Fake.calls == ["deep"]                               # so it never asked a model; the deep step did
    assert airecord.proposal_path(w["merged"], 1).read_bytes() == _Fake.deep_writes
    rec = airecord.load(airecord.record_path(w["merged"]))
    assert airecord.answer_kind(rec.answers[0]) == "mechanical" and rec.answers[0]["backend"] == "git"
    assert rec.chosen == 0
    assert not airecord.proposal_path(w["merged"]).exists()       # no bare .merged-ai for git's own result


def test_live_root_of_a_path_that_is_exactly_target_and_rel_is_none_M18():
    """v0.6.5 sweep, survivor M18: `strip >= len(parts)` -- a relative live
    path with nothing above the territory has no root, and `Path()` (the
    process's cwd) is the one answer that must never be returned."""
    from types import SimpleNamespace
    entry = SimpleNamespace(target="skills")
    assert merge._live_root_of(SimpleNamespace(entry=entry, rel="s.md", live=Path("skills/s.md"))) is None
    assert merge._live_root_of(SimpleNamespace(entry=entry, rel="s.md",
                                               live=Path("C:/live/skills/s.md"))) == Path("C:/live")
    assert merge._live_root_of(SimpleNamespace(entry=SimpleNamespace(target=None), rel="",
                                               live=Path("C:/live/x"))) is None


def test_options_without_a_plan_still_run_the_recipe_M19(tmp_path):
    """v0.6.5 sweep, survivor M19: every caller from before the plan existed
    builds `AiOptions` with no steps and means the recipe on `backend`."""
    from dazzle_claude_config import aistep
    opts = aistep.AiOptions(rules_dir=tmp_path, prompts_dir=tmp_path, cache_dir=tmp_path, backend="claude")
    assert [(s.kind, s.backend) for s in opts.plan()] == [("recipe", "claude")]
    with_steps = aistep.AiOptions(rules_dir=tmp_path, prompts_dir=tmp_path, cache_dir=tmp_path,
                                  backend="claude",
                                  steps=(aistep.AiStep("recipe", "claude"), aistep.AiStep("deep", "codex")))
    assert [(s.kind, s.backend) for s in with_steps.plan()] == [("recipe", "claude"), ("deep", "codex")]


# -- #63: the identity without empty fields ------------------------------------------------

def test_63_no_identity_carries_an_empty_field_and_every_part_is_labelled():
    from dazzle_claude_config import ailib
    for name in ailib.PRESETS:
        ident = ailib.spec_for(name, keys_dir=Path("C:/k")).identity()
        assert "||" not in ident and not ident.endswith("|"), (name, ident)
        assert ident.startswith(ailib.PRESETS[name].transport + " "), ident
        if ailib.PRESETS[name].transport == "cli":
            assert "command=" in ident and "endpoint=" not in ident
        else:
            assert "endpoint=" in ident and "command=" not in ident
    assert "key:OPENROUTER_API_KEY" in ailib.spec_for("openrouter").identity()   # the pinned spellings stand
    assert "keyfile:openrouter.env" in ailib.spec_for("openrouter", keys_dir=Path("C:/k")).identity()


# -- U7: the latitude design's moves that are code (N1, N3) and the plan's default ---------

def test_reserved_characters_in_a_step_are_refused_by_name_N1():
    """The latitude design (2026-09-15), move N1: `@` and `/` inside a step
    token are reserved for a later per-step latitude syntax
    (`deep@file/minimal`), so nobody's plan comes to depend on them meaning
    something else. The refusal says so; it is not "unknown backend"."""
    for token in ("deep@file", "claude,deep@hunk/minimal", "deep:claude/minimal", "claude@file"):
        with pytest.raises(ValueError, match="reserved for a later per-step latitude syntax") as e:
            _plan(token)
        # the sentence carries the spelling that exists today, so the person is
        # sent somewhere real (v0.6.7 sweep, survivor M3)
        assert "--ai <preset>,deep --ai-scope <rung>" in str(e.value)
    assert _plan("claude,deep") == [("recipe", "claude"), ("deep", "claude")]      # the shipped spelling stands


_CLEAN_BASE = b"# skill\nintro\n\nrule A\nrule B\nrule C\n\nnotes\n"
_CLEAN_OURS = b"# skill\nintro, expanded locally\n\nrule A\nrule B\nrule C\n\nnotes\n"
_CLEAN_THEIRS = b"# skill\nintro\n\nrule A\nrule B\nrule C\n\nnotes, revised upstream\n"


def test_a_clean_merge_speaks_in_hunks_of_both_kinds_and_names_the_deep_step_N3(tmp_path, capsys, fake_cli):
    """The maintainer's vocabulary (2026-09-15): a diff-hunk is a region one
    side changed and git took on its own; a conflict-hunk is a region both
    sides changed, with three panes. The clean-merge line says which kind
    there was none of, which kind git took, and -- when no deep step ran --
    that `,deep` is what reads the diff-hunks together. That nudge is the
    founding case's report line: a clean merge is not a resolved one."""
    w = _world(tmp_path, history=(_CLEAN_BASE, _CLEAN_THEIRS), live=_CLEAN_OURS)
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "claude", "--no-launch"))
    out = capsys.readouterr().out
    assert rc == EXIT_CLEAN, out
    assert "no conflict-hunk" in out and "diff-hunks" in out and "add ,deep" in out, out
    assert "no hunk both sides changed" not in out
    # with a deep step in the plan the deep line follows and the nudge is gone
    w2 = _world(tmp_path / "two", history=(_CLEAN_BASE, _CLEAN_THEIRS), live=_CLEAN_OURS)
    _Fake.deep_writes = None
    main(_ccs(w2, "merge", "skills/s.md", "--ai", "claude,deep", "--no-launch"))
    out2 = capsys.readouterr().out
    assert "no conflict-hunk" in out2 and "add ,deep" not in out2, out2
    assert "nothing to change" in out2


def test_the_count_line_names_conflict_hunks_and_diff_hunks_N3(tmp_path, capsys, fake_cli):
    """The recipe's first line under the headline, in the vocabulary: how
    many conflict-hunks the model was given, how many lines in diff-hunks
    git took on its own and never sent."""
    w = _world(tmp_path)
    main(_ccs(w, "merge", "skills/s.md", "--ai", "claude", "--no-launch"))
    out = capsys.readouterr().out
    line = next((ln.strip() for ln in out.splitlines() if ln.strip().startswith("conflict-hunks:")), "")
    assert line.startswith("conflict-hunks: 1 -- the model's;"), out
    assert "in diff-hunks git took on its own, never sent" in line, line
    assert "both sides changed" not in out
    # a file that is nothing but the conflict-hunk: zero lines in diff-hunks,
    # and the plural still reads (v0.6.7 sweep, survivor M4)
    w0 = _world(tmp_path / "zero", history=(b"a\n", b"c\n"), live=b"b\n")
    main(_ccs(w0, "merge", "skills/s.md", "--ai", "prompt-only", "--no-launch"))
    out0 = capsys.readouterr().out
    assert "conflict-hunks: 1 -- the model's; 0 lines in diff-hunks" in out0, out0


def test_options_fill_the_recipe_plan_at_construction_so_nothing_falls_back_later(tmp_path):
    """U7, from the latitude design's note on `AiOptions.plan()`: the
    pre-plan default is filled in when the options are built, so `steps` is
    never empty and no caller reaches a defaulted branch by mistake --
    the shape is impossible rather than handled."""
    from dazzle_claude_config import aistep
    opts = aistep.AiOptions(rules_dir=tmp_path, prompts_dir=tmp_path, cache_dir=tmp_path, backend="claude")
    assert opts.steps == (aistep.AiStep("recipe", "claude"),)
    assert opts.plan() == opts.steps
    assert opts.scope == 1                       # hunk: the narrowest rung is the default (v0.6.7 sweep, M10)
    kept = aistep.AiOptions(rules_dir=tmp_path, prompts_dir=tmp_path, cache_dir=tmp_path, backend="claude",
                            steps=(aistep.AiStep("recipe", "claude"), aistep.AiStep("deep", "codex")))
    assert [(s.kind, s.backend) for s in kept.steps] == [("recipe", "claude"), ("deep", "codex")]
