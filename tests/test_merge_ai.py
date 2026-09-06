"""a5c -- `ccs merge --ai`, wired: the verb, the workspace, the record, the words.

Through `main()` on a real git world: a checkout with two commits (the
second is the payload's change), a live file that changed the same line
differently, so the inferred base is the first commit and the merge has
exactly one conflict hunk -- a paragraph, as the real workspace's only
one was. Nothing here installs a byte without `--accept`, and `--accept`
on a proposal the person never touched asks first.
"""
from __future__ import annotations

import json
import subprocess as sp
from pathlib import Path

import pytest

from dazzle_claude_config import airecord, aistep, merge
from dazzle_claude_config.cli import EXIT_CLEAN, EXIT_DRIFT, EXIT_ERROR, main
from dazzle_claude_config.seeddecisions import norm_sha

from conftest import GIT_ID

MANIFEST = {
    "manifest_version": 1,
    "territories": {"dotclaude": {"root_var": "CLAUDE_DIR", "repo_dir": "dotclaude"}},
    "entries": [{"repo": "dotclaude/skills", "territory": "dotclaude",
                 "target": "skills", "strategy": "copy"}],
}

V1 = b"# skill\nrule A\nrule B\n"
V2 = b"# skill\nrule A revised upstream\nrule B\n"          # the payload's change (HEAD)
LIVE = b"# skill\nrule A locally revised\nrule B\n"         # the box's change, same line
GOOD = {"hunks": [{"hunk": 1, "lines": ["T1"], "rules": [], "rationale": "upstream's wording"}]}
PROPOSAL = V2                                                # take theirs on the one hunk


def _git(cwd: Path, *args: str) -> None:
    r = sp.run(["git", *GIT_ID, "-C", str(cwd), *args], capture_output=True, text=True)
    assert r.returncode == 0, f"git {args}: {r.stderr}"


def _world(tmp_path: Path, history=(V1, V2), live: bytes = LIVE) -> dict:
    co, live_dir, user = tmp_path / "co", tmp_path / "live", tmp_path / "user"
    (co / "dotclaude" / "skills").mkdir(parents=True)
    (live_dir / "skills").mkdir(parents=True)
    user.mkdir()
    (co / "ccs-manifest.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    sp.run(["git", "init", "-q", "-b", "main", str(co)], check=True)
    target = co / "dotclaude" / "skills" / "s.md"
    for i, content in enumerate(history):
        target.write_bytes(content)
        if i == 0:
            _git(co, "add", "-A")
            _git(co, "commit", "-qm", "v1")
        else:
            _git(co, "commit", "-qam", f"v{i + 1}")
    (live_dir / "skills" / "s.md").write_bytes(live)
    ws = user / "merge" / "ccs"
    return dict(co=co, live=live_dir, user=user, ws=ws,
                merged=ws / "skills__s.md.merged", live_file=live_dir / "skills" / "s.md")


def _ccs(w: dict, *verb: str) -> list[str]:
    return ["--checkout-dir", str(w["co"]), "--claude-dir", str(w["live"]),
            "--user-claude", str(w["user"]), "--no-color", "--no-fetch", *verb]


def _answer(tmp_path, data=GOOD) -> Path:
    p = tmp_path / "answer.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _staged(w, tmp_path, capsys):
    """A canned answer, staged and copied; the state the later tests start from."""
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "--ai-response", str(_answer(tmp_path)),
                   "--no-launch"))
    return rc, capsys.readouterr().out


# -- the floor -----------------------------------------------------------------

def test_prompt_only_writes_the_prompt_and_prints_the_paragraph_report(tmp_path, capsys):
    w = _world(tmp_path)
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "prompt-only", "--no-launch"))
    out = capsys.readouterr().out
    assert "prompt written" in out, out
    assert "both sides rewrote the same paragraph" in out
    assert "--ai-response" in out and "skills__s.md.merged-ai.response.json" in out
    assert len(list((w["user"] / "ccs-merge-rules" / "_prompts").glob("skills__s.md-*.md"))) == 1
    assert not airecord.proposal_path(w["merged"]).exists()
    assert "NOT INSTALLED" not in out                 # a prompt is not a failed merge
    assert rc == EXIT_DRIFT                            # work is pending
    assert w["live_file"].read_bytes() == LIVE


# -- a proposal -----------------------------------------------------------------

def test_a_canned_answer_is_staged_and_copied_when_you_had_no_result(tmp_path, capsys):
    w = _world(tmp_path)
    rc, out = _staged(w, tmp_path, capsys)
    assert "the AI's proposal" in out and "copied into" in out, out
    proposal = airecord.proposal_path(w["merged"])
    assert proposal.read_bytes() == PROPOSAL
    assert w["merged"].read_bytes() == PROPOSAL
    rec = airecord.load(airecord.record_path(w["merged"]))
    assert rec is not None and rec.valid and rec.copied_sha == norm_sha(PROPOSAL)
    assert rec.backend == "prompt-only" and rec.base_kind == "inferred"
    assert "upstream's wording" in out                # the rationale is printed
    assert "nothing installed" in out
    assert "unchanged since" not in out               # M17: said once, on the proposal's line
    assert w["live_file"].read_bytes() == LIVE         # nothing installed, indeed
    assert rc == EXIT_CLEAN


def test_the_next_bare_merge_reads_the_copy_as_the_ais_not_yours(tmp_path, capsys):
    w = _world(tmp_path)
    _staged(w, tmp_path, capsys)
    rc = main(_ccs(w, "merge", "skills/s.md", "--no-launch"))
    out = capsys.readouterr().out
    assert "the AI's proposal, unchanged since" in out, out
    assert "keeping it as yours" not in out
    assert w["merged"].read_bytes() == PROPOSAL        # not re-seeded over
    assert rc == EXIT_CLEAN


def test_an_edited_copy_reads_as_yours_and_names_the_difference(tmp_path, capsys):
    w = _world(tmp_path)
    _staged(w, tmp_path, capsys)
    w["merged"].write_bytes(PROPOSAL + b"a line of my own\n")
    main(_ccs(w, "merge", "skills/s.md", "--no-launch"))
    out = capsys.readouterr().out
    assert "yours; differs from the AI's proposal (1 line" in out, out
    assert "ccs diff skills/s.md --ai" in out
    assert "--accept installs YOURS" in out


def test_a_moved_side_makes_the_unchanged_proposal_stale(tmp_path, capsys):
    w = _world(tmp_path)
    _staged(w, tmp_path, capsys)
    w["live_file"].write_bytes(b"# skill\nrule A locally revised twice\nrule B\n")
    main(_ccs(w, "merge", "skills/s.md", "--no-launch"))
    out = capsys.readouterr().out
    assert "your live file has changed since" in out, out


# -- --accept ------------------------------------------------------------------

def test_accept_on_an_unreviewed_proposal_asks_and_a_non_interactive_run_declines(tmp_path, capsys, monkeypatch):
    w = _world(tmp_path)
    _staged(w, tmp_path, capsys)
    monkeypatch.setattr(merge, "interactive", lambda: False)
    rc = main(_ccs(w, "merge", "skills/s.md", "--accept", "--no-launch"))
    out = capsys.readouterr().out
    assert "not confirmed as reviewed" in out, out
    assert w["live_file"].read_bytes() == LIVE
    assert rc == EXIT_DRIFT


def test_accept_after_a_yes_installs_and_records_it_so_it_is_not_asked_twice(tmp_path, capsys, monkeypatch):
    w = _world(tmp_path)
    _staged(w, tmp_path, capsys)
    asked = []
    monkeypatch.setattr(merge, "_ask_ai_on_console", lambda item, rec: asked.append(item.label) or True)
    rc = main(_ccs(w, "merge", "skills/s.md", "--accept", "--no-launch"))
    out = capsys.readouterr().out
    assert asked == ["skills/s.md"]
    assert w["live_file"].read_bytes() == PROPOSAL
    assert "installed" in out and rc == EXIT_CLEAN
    rec = airecord.load(airecord.record_path(w["merged"]))
    assert rec.accepted_unchanged                      # the keystroke, recorded


def test_the_question_names_the_proposal_and_defaults_to_no(tmp_path, capsys, monkeypatch):
    w = _world(tmp_path)
    _staged(w, tmp_path, capsys)
    monkeypatch.setattr(merge, "interactive", lambda: True)
    prompts: list[str] = []
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt) or "")
    rc = main(_ccs(w, "merge", "skills/s.md", "--accept", "--no-launch"))
    out = capsys.readouterr().out
    assert "the AI's proposal, unchanged since ccs wrote it" in out, out
    assert prompts and "[y/N]" in prompts[0] and "ccs diff skills/s.md --ai" in prompts[0]
    assert "nothing to do" not in out                 # a declined proposal is not "nothing"
    assert w["live_file"].read_bytes() == LIVE and rc == EXIT_DRIFT


def test_a_proposal_the_validator_refuses_is_reported_rejected_and_never_copied(tmp_path, capsys):
    """Mutation survivor M6 (v0.5.21 sweep): the validator is the backstop on
    the assembled file, and it still refuses what the answer's own check
    cannot see. A rules file licenses DROPS and nothing else -- here the
    answer drops nothing controversial and simply takes a payload line that
    carries a pattern this box fixed locally, which the file-level gate
    catches and no per-hunk rule can wave through. The file is left on disk
    for the person's eyes and nothing is copied."""
    regressed = b"# skill\npaths live under /home/dev/claude/ now\nrule B\n"
    w = _world(tmp_path, live=b"# skill\nrule A local\nrule B\n", history=(V1, regressed))
    rules = w["user"] / "ccs-merge-rules"
    rules.mkdir(parents=True)
    (rules / "_default.md").write_text("TAKE theirs in every conflict.\n", encoding="utf-8")
    answer = _answer(tmp_path, {"hunks": [{"hunk": 1, "lines": ["T1"], "rules": ["R1"],
                                           "rationale": "theirs, per R1"}]})
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "--ai-response", str(answer), "--no-launch"))
    out = capsys.readouterr().out
    assert "NOT PROPOSED" in out and "regressed pattern" in out, out
    assert "for your eyes" in out and "copied into" not in out
    assert airecord.proposal_path(w["merged"]).is_file()
    rec = airecord.load(airecord.record_path(w["merged"]))
    assert rec.valid is False and rec.copied_sha == ""
    assert b"<<<<<<<" in w["merged"].read_bytes()       # the seed, not the proposal
    assert rc == merge.EXIT_VALIDATION


def test_ai_with_no_value_and_no_config_means_prompt_only(tmp_path, capsys):
    """Mutation survivor M14: the floor is the default."""
    w = _world(tmp_path)
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "--no-launch"))
    out = capsys.readouterr().out
    assert "prompt written" in out and "unknown AI backend" not in out, out
    assert rc == EXIT_DRIFT


def test_a_proposal_is_not_copied_over_a_result_you_edited(tmp_path, capsys):
    """Mutation survivor M16, sharpened: the copy rule reads whether the
    person has work of their own there, and an edit in the merge tool is
    exactly that -- the proposal lands beside it, the file stays theirs."""
    w = _world(tmp_path)
    main(_ccs(w, "merge", "skills/s.md", "--no-launch"))        # seeds .merged (with markers)
    capsys.readouterr()
    mine = b"# skill\nrule A, resolved by hand\nrule B\n"
    w["merged"].write_bytes(mine)                               # their own resolution
    main(_ccs(w, "merge", "skills/s.md", "--ai", "--ai-response", str(_answer(tmp_path)), "--no-launch"))
    out = capsys.readouterr().out
    assert "the AI's proposal" in out and "copied into" not in out, out
    assert w["merged"].read_bytes() == mine
    assert airecord.proposal_path(w["merged"]).read_bytes() == PROPOSAL


def test_a_proposal_beside_a_file_you_resolved_yourself_is_still_reported(tmp_path, capsys):
    """The third record state, `not-copied`, which the report used to pass
    over in silence: the person resolved the file before asking, so the copy
    rule never fired and a proposal now sits beside their work with nothing
    saying how far apart they are. Found by a tester walking HV.3's
    copy-rule-scope step, 2026-09-04."""
    w = _world(tmp_path)
    main(_ccs(w, "merge", "skills/s.md", "--no-launch"))            # seeds
    mine = b"# skill\nrule A locally revised\nrule B\nand a line of my own\n"
    w["merged"].write_bytes(mine)                                   # their own resolution
    main(_ccs(w, "merge", "skills/s.md", "--ai", "--ai-response", str(_answer(tmp_path)),
              "--no-launch"))                                       # a proposal lands beside it
    capsys.readouterr()
    main(_ccs(w, "merge", "skills/s.md", "--no-launch"))            # the next look
    out = capsys.readouterr().out
    assert "yours; differs from the AI's proposal" in out, out
    assert "--accept installs YOURS" in out
    assert w["merged"].read_bytes() == mine                         # untouched throughout


# -- a drop the person's own rules authorised ------------------------------------

LIVE_FAR = b"# skill\nnothing of the kind happens on this host at all\nrule B\n"
RULES_FAR = b"KEEP every line that mentions rule B.\n\nA line this host has no use for may go.\n"
DROP_R2 = {"hunks": [{"hunk": 1, "lines": ["T1"], "rules": ["R2"],
                      "rationale": "the payload's wording; R2 lets ours go"}]}


def _far_world(tmp_path):
    """A hunk whose two sides share almost no words, so taking one side is a
    DROP of the other and not a rewrite of it -- the shape a rules file
    exists for."""
    w = _world(tmp_path, live=LIVE_FAR)
    (w["user"] / "ccs-merge-rules").mkdir(parents=True)
    (w["user"] / "ccs-merge-rules" / "_default.md").write_bytes(RULES_FAR)
    return w


def test_a_drop_a_cited_rule_authorised_reaches_staged(tmp_path, capsys):
    """The feature's whole point for a forked box, and it did not work.

    `check_proposal` licensed the drop and the file-level `validate` --
    which reads the result against the two sides and has never heard of a
    rules file -- refused it one line later, so a rules file could never
    authorise the one thing it is for. Measured on a scratch world by a
    tester walking section 2.2 of the checklist, 2026-09-04.
    """
    w = _far_world(tmp_path)
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai",
                   "--ai-response", str(_answer(tmp_path, DROP_R2)), "--no-launch"))
    out = capsys.readouterr().out
    assert "staged" in out and "validation passed" in out, out
    assert "NOT PROPOSED" not in out and "NOT INSTALLED" not in out, out
    # the drop is never silent: the line, and the rule that let it go
    assert "dropped under R2" in out and "nothing of the kind happens" in out, out
    assert w["merged"].read_bytes() == PROPOSAL
    rec = airecord.load(airecord.record_path(w["merged"]))
    assert rec is not None and rec.valid
    assert any("nothing of the kind" in ln for ln in rec.licensed), rec.licensed
    assert rc == EXIT_CLEAN


def test_the_record_carries_the_licence_into_later_runs(tmp_path, capsys):
    """A bare merge tomorrow reads the same file. Without the licence in the
    record it would refuse what it called valid today."""
    w = _far_world(tmp_path)
    main(_ccs(w, "merge", "skills/s.md", "--ai",
              "--ai-response", str(_answer(tmp_path, DROP_R2)), "--no-launch"))
    capsys.readouterr()
    rc = main(_ccs(w, "merge", "skills/s.md", "--no-launch"))          # no --ai
    out = capsys.readouterr().out
    assert "the AI's proposal, unchanged since" in out, out
    assert "NOT INSTALLED" not in out and "dropped:" not in out, out
    assert rc == EXIT_CLEAN


def test_the_licence_is_exactly_as_wide_as_the_rules(tmp_path, capsys):
    """The same drop with no rule cited is still refused, by name. The
    subtraction narrows the gate by what the person wrote down, not by the
    fact that an AI was involved."""
    w = _far_world(tmp_path)
    nocite = {"hunks": [{"hunk": 1, "lines": ["T1"], "rules": []}]}
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai",
                   "--ai-response", str(_answer(tmp_path, nocite)), "--no-launch"))
    out = capsys.readouterr().out
    assert "NOT PROPOSED" in out and "dropped with no rule cited" in out, out
    assert "staged" not in out
    assert rc == EXIT_ERROR or rc == 4                     # validation, nothing installed


def test_the_two_step_flow_copies_over_the_seed_nobody_touched(tmp_path, capsys):
    """The flow the feature is actually used through: one run writes the
    prompt (and seeds .merged with conflict markers, as any merge run does),
    the next carries the answer back. That seed is ccs's own scaffold --
    `run` re-seeds it four lines above the copy rule -- so the proposal is
    copied over it, and the run does not end on `NOT INSTALLED ... unresolved
    conflict markers` printed over ccs's own markers. Measured on a scratch
    world, where the two-step flow did exactly that."""
    w = _world(tmp_path)
    main(_ccs(w, "merge", "skills/s.md", "--ai", "--no-launch"))        # prompt + seed
    capsys.readouterr()
    assert b"<<<<<<<" in w["merged"].read_bytes()
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "--ai-response", str(_answer(tmp_path)),
                   "--no-launch"))
    out = capsys.readouterr().out
    assert "copied into" in out and "no result of your own" in out, out
    assert "NOT INSTALLED" not in out and "unresolved conflict markers" not in out, out
    assert w["merged"].read_bytes() == PROPOSAL
    rec = airecord.load(airecord.record_path(w["merged"]))
    assert rec is not None and rec.copied_sha == norm_sha(PROPOSAL)
    assert w["live_file"].read_bytes() == LIVE                  # still nothing installed
    assert rc == EXIT_CLEAN


def test_a_deleted_result_is_reseeded_and_not_called_the_ais_or_yours(tmp_path, capsys):
    """Mutation survivor N2 (round 2): a record with no .merged beside it
    describes nothing on disk; the fresh seed is neither the AI's nor an
    edit of it."""
    w = _world(tmp_path)
    _staged(w, tmp_path, capsys)
    w["merged"].unlink()
    main(_ccs(w, "merge", "skills/s.md", "--no-launch"))
    out = capsys.readouterr().out
    assert "differs from the AI's proposal" not in out and "unchanged since" not in out, out
    assert b"<<<<<<<" in w["merged"].read_bytes()


def test_an_edited_result_whose_proposal_was_deleted_does_not_crash(tmp_path, capsys):
    """Mutation survivor N5: the difference can only be counted against a
    proposal that is still there."""
    w = _world(tmp_path)
    _staged(w, tmp_path, capsys)
    airecord.proposal_path(w["merged"]).unlink()
    w["merged"].write_bytes(LIVE)                        # edited back to a side: valid
    rc = main(_ccs(w, "merge", "skills/s.md", "--no-launch"))
    out = capsys.readouterr().out
    assert "differs from the AI's proposal" not in out
    assert rc == EXIT_CLEAN


def test_accept_in_the_same_run_as_the_copy_still_asks(tmp_path, capsys, monkeypatch):
    """Mutation survivor N9: the proposal copied into an absent .merged is an
    unreviewed proposal from that moment; --accept in the SAME run must ask,
    and a non-interactive run must not install it."""
    w = _world(tmp_path)
    monkeypatch.setattr(merge, "interactive", lambda: False)
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "--ai-response", str(_answer(tmp_path)),
                   "--no-launch", "--accept"))
    out = capsys.readouterr().out
    assert "not confirmed as reviewed" in out, out
    assert w["live_file"].read_bytes() == LIVE
    assert rc == EXIT_DRIFT


def test_confirm_ai_is_the_injection_point_for_the_question(tmp_path, capsys, monkeypatch):
    """Mutation survivor N10: a caller may supply the question (as
    `confirm_loss` is supplied); the console is only the default."""
    from dazzle_claude_config.manifest import Manifest
    w = _world(tmp_path)
    _staged(w, tmp_path, capsys)

    def console_must_not_be_asked(*a):
        raise AssertionError("the console prompt ran despite confirm_ai")
    monkeypatch.setattr(merge, "_ask_ai_on_console", console_must_not_be_asked)
    seen: list[str] = []
    manifest = Manifest.load(w["co"])
    roots = {"CLAUDE_DIR": w["live"], "USER_CLAUDE": w["user"]}
    r = merge.run(manifest, w["co"], roots, only="dotclaude/skills/s.md", launch_tool=False,
                  accept=True, confirm_ai=lambda item, rec: seen.append(item.label) or True)
    assert seen == ["skills/s.md"]
    assert [i.label for i in r.resolved] == ["skills/s.md"]
    assert w["live_file"].read_bytes() == PROPOSAL


def test_base_kind_names_how_the_base_was_chosen(tmp_path):
    """Mutation survivor N11: a sibling that exists but was NOT used as the
    base does not make the kind 'sibling'."""
    from dazzle_claude_config.merge import MergeItem, _base_kind
    from dazzle_claude_config.manifest import Entry
    entry = Entry(repo="dotclaude/x", territory="dotclaude", target="x", strategy="copy")
    sib = tmp_path / "sib"
    base = tmp_path / "base"
    item = MergeItem(entry=entry, rel="", live=tmp_path / "l", repo=tmp_path / "r",
                     base=base, sibling=(sib, "abc1234", 3, 0.5))
    assert _base_kind(item) == "inferred"
    item.base = sib
    assert _base_kind(item) == "sibling"
    item.base_supplied = True
    assert _base_kind(item) == "supplied"


# -- refusals ------------------------------------------------------------------

def test_no_common_ancestor_refuses_the_step_before_any_prompt(tmp_path, capsys):
    w = _world(tmp_path, history=(V2,))               # a one-commit history: no base
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "prompt-only", "--no-launch"))
    out = capsys.readouterr().out
    assert "no common ancestor" in out and "two-way guess" in out, out
    assert not (w["user"] / "ccs-merge-rules").exists()
    assert rc == merge.EXIT_NO_BASE


def test_an_unknown_backend_is_refused_with_the_names(tmp_path, capsys):
    w = _world(tmp_path)
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "gpt9", "--no-launch"))
    out = capsys.readouterr().out
    assert "gpt9" in out and "claude" in out and "codex" in out and "prompt-only" in out
    assert rc == EXIT_ERROR


# -- the config key and a live backend -----------------------------------------

def test_the_config_key_picks_the_backend_when_ai_has_no_value(tmp_path, capsys, monkeypatch):
    w = _world(tmp_path)
    (w["user"] / "ccs-config.json").write_text(json.dumps({"ai_merge_backend": "claude"}), encoding="utf-8")
    reply = "```json\n" + json.dumps(GOOD) + "\n```"
    # a fake TRANSPORT under the name the claude preset uses: the real preset,
    # backend, cache and record run; only the subprocess is faked
    from dazzle_claude_config._vendor.ailib import backend as _bm
    from dazzle_claude_config._vendor.ailib.types import Readiness, Response

    class _T:
        def probe(self, spec): return Readiness(True, "fake")
        def invoke(self, spec, req): return Response("answered", text=reply, model_used="fake")
        def capabilities(self, spec): return frozenset({"model", "schema"})

    _bm.transport_for("cli")
    monkeypatch.setitem(_bm._TRANSPORTS, "cli", _T())
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "--no-launch"))
    out = capsys.readouterr().out
    assert "(claude)" in out, out
    assert airecord.load(airecord.record_path(w["merged"])).backend == "claude"
    assert rc == EXIT_CLEAN


# -- diff --ai -----------------------------------------------------------------

def test_diff_ai_opens_the_proposal_beside_yours(tmp_path, capsys, monkeypatch):
    w = _world(tmp_path)
    _staged(w, tmp_path, capsys)
    opened = []
    monkeypatch.setattr(merge, "resolve_difftool", lambda explicit=None: "faketool")
    monkeypatch.setattr(merge, "launch_difftool", lambda name, left, right: opened.append((name, left, right)) or 0)
    rc = main(_ccs(w, "diff", "skills/s.md", "--ai"))
    out = capsys.readouterr().out
    assert opened == [("faketool", airecord.proposal_path(w["merged"]), w["merged"])]
    assert "the AI's proposal" in out and rc == EXIT_CLEAN


def test_diff_ai_without_a_proposal_says_so(tmp_path, capsys):
    w = _world(tmp_path)
    rc = main(_ccs(w, "diff", "skills/s.md", "--ai"))
    out = capsys.readouterr().out
    assert "no AI proposal" in out and "--ai" in out
    assert rc == EXIT_CLEAN


# -- #19, criteria 1 and 2: the counts come first, and the model sees only the hunks --

def _one_sided_world(tmp_path):
    """Twenty lines. Ours alone rewrote line 2; theirs alone rewrote line 18;
    both rewrote line 10. diff3 resolves the two one-sided edits itself and
    leaves exactly one hunk -- the model must see that hunk and nothing of
    the other two, which sit well outside any context window."""
    base = "".join(f"line {i}\n" for i in range(1, 21)).encode()
    ours = base.replace(b"line 2\n", b"OURS ALONE changed two\n").replace(b"line 10\n", b"ten by ours\n")
    theirs = base.replace(b"line 18\n", b"THEIRS ALONE changed eighteen\n").replace(b"line 10\n", b"ten by theirs\n")
    return _world(tmp_path, history=(base, theirs), live=ours)


def test_the_counts_come_first_and_one_sided_lines_never_reach_the_prompt(tmp_path, capsys):
    w = _one_sided_world(tmp_path)
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "prompt-only", "--no-launch"))
    out = capsys.readouterr().out
    assert rc in (EXIT_CLEAN, EXIT_DRIFT), out
    lines = out.splitlines()
    head = next(i for i, l in enumerate(lines) if l.startswith("prompt written"))
    # criterion 1: the classification counts, before anything else about the file
    assert lines[head + 1].strip().startswith("hunks: 1 both sides changed"), lines[head + 1]
    assert "19 lines git resolved on its own, never sent" in lines[head + 1], lines[head + 1]
    # criterion 2: the two one-sided edits are in the merged result and NOT in the prompt
    prompts = list((w["user"] / "ccs-merge-rules" / "_prompts").glob("*.md"))
    assert len(prompts) == 1, prompts
    prompt = prompts[0].read_text(encoding="utf-8")
    assert "ten by ours" in prompt and "ten by theirs" in prompt
    assert "OURS ALONE" not in prompt and "THEIRS ALONE" not in prompt, prompt


def test_the_counts_come_first_on_a_staged_proposal_too(tmp_path, capsys):
    w = _one_sided_world(tmp_path)
    answer = {"hunks": [{"hunk": 1, "lines": ["T1"], "rules": [], "rationale": "a rewrite"}]}
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "--ai-response",
                   str(_answer(tmp_path, answer)), "--no-launch"))
    out = capsys.readouterr().out
    assert rc in (EXIT_CLEAN, EXIT_DRIFT), out
    lines = out.splitlines()
    head = next(i for i, l in enumerate(lines) if l.startswith("staged"))
    assert lines[head + 1].strip().startswith("hunks: 1 both sides changed"), lines[head + 1]
    assert "rules:" in lines[head + 2] or "no rules" in lines[head + 2], lines[head + 2]
    merged = w["merged"].read_bytes()
    assert b"OURS ALONE" in merged and b"THEIRS ALONE" in merged and b"ten by theirs" in merged
