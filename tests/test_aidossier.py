"""a0 -- the ancestry dossier: what ccs knows about a file's history, in
plain words, for the model to reason over.

Evidence, never a decision: ccs chose the base (the same `infer_base` the
status verb and the guards call -- no second walker); the dossier lists
the base and how, the hints the terminal prints, the other versions in the
checkout's history nearest-first with the caveat that distance is a weak
ranking, whether the payload's copy in the checkout is committed or an
uncommitted edit, the remote leg, and whether the live tree has its own
git history for the file. The structured facts join the cache key; the
prose does not. The live probe reads and never writes -- pinned twice.
"""
from __future__ import annotations

import hashlib
import json
import subprocess as sp
from pathlib import Path

import pytest

from dazzle_claude_config import livegit, merge
from dazzle_claude_config.cli import main
from dazzle_claude_config.manifest import Manifest

from conftest import GIT_ID
from test_merge_ai import LIVE, V1, V2, _ccs, _world


def _git(cwd: Path, *args: str) -> str:
    r = sp.run(["git", *GIT_ID, "-C", str(cwd), *args], capture_output=True, text=True)
    assert r.returncode == 0, f"git {args}: {r.stderr}"
    return r.stdout


# -- infer_base's candidate list -------------------------------------------------

def test_infer_base_reports_every_candidate_with_its_date(tmp_path):
    w = _world(tmp_path)
    cands: list = []
    found = merge.infer_base(w["co"], "dotclaude/skills/s.md", LIVE, V2, candidates=cands)
    assert found is not None
    blob, sha = found
    assert blob == V1 and len(sha) == 7
    assert len(cands) == 2
    shas = {c.sha for c in cands}
    assert sha in shas and all(len(s) == 7 for s in shas)
    assert all(c.date.startswith("20") and len(c.date) == 10 for c in cands)   # YYYY-MM-DD
    assert sum(c.eq_theirs for c in cands) == 1
    assert all(isinstance(c.score, int) and c.score >= 0 for c in cands)
    assert not any(c.exact for c in cands)


def test_infer_base_marks_where_the_search_stopped_at_an_exact_match(tmp_path):
    w = _world(tmp_path, live=V1)                     # live IS the first commit
    cands: list = []
    merge.infer_base(w["co"], "dotclaude/skills/s.md", V1, V2, candidates=cands)
    assert cands and cands[-1].exact is True
    assert all(not c.exact for c in cands[:-1])


def test_a_caller_that_passes_no_list_sees_no_change(tmp_path):
    w = _world(tmp_path)
    assert merge.infer_base(w["co"], "dotclaude/skills/s.md", LIVE, V2) == (V1, merge.infer_base(
        w["co"], "dotclaude/skills/s.md", LIVE, V2)[1])


# -- the item carries the facts --------------------------------------------------

def _plan_item(w, tmp_path):
    manifest = Manifest.load(w["co"])
    roots = {"CLAUDE_DIR": w["live"], "USER_CLAUDE": w["user"]}
    items = merge.plan(manifest, w["co"], roots, stage=tmp_path / "stage")
    return next(i for i in items if i.label == "skills/s.md")


def test_the_planned_item_carries_the_candidates_and_the_working_tree_fact(tmp_path):
    w = _world(tmp_path)
    item = _plan_item(w, tmp_path)
    assert len(item.candidates) == 2
    assert item.checkout_state == "committed"


def test_an_uncommitted_edit_in_the_checkout_is_a_fact_on_the_item(tmp_path):
    w = _world(tmp_path)
    (w["co"] / "dotclaude" / "skills" / "s.md").write_bytes(V2 + b"working-tree edit\n")
    item = _plan_item(w, tmp_path)
    assert item.checkout_state == "modified"


def test_checkout_states_reads_modified_untracked_and_renamed(tmp_path):
    """Mutation survivors M8/M9 (v0.5.21 sweep): the porcelain codes, read
    right -- `??` is untracked, a rename reports its NEW path."""
    repo = tmp_path / "co"
    (repo / "d").mkdir(parents=True)
    sp.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    for name in ("keep.md", "edit.md", "old.md", "with space.md"):
        (repo / "d" / name).write_text(name + "\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    (repo / "d" / "edit.md").write_text("changed\n", encoding="utf-8")
    (repo / "d" / "with space.md").write_text("changed\n", encoding="utf-8")
    (repo / "d" / "new.md").write_text("new\n", encoding="utf-8")
    _git(repo, "mv", "d/old.md", "d/moved.md")
    states = merge._checkout_states(repo)
    assert states["d/edit.md"] == "modified"
    assert states["d/new.md"] == "untracked"
    assert states["d/moved.md"] == "modified" and "d/old.md" not in states
    assert states["d/with space.md"] == "modified"   # N4: porcelain quotes it; the key is bare
    assert "d/keep.md" not in states


def test_the_candidates_are_listed_nearest_first(tmp_path):
    """Mutation survivor M11: nearest to the live file first, by distance."""
    V0 = b"# skill\nsomething else entirely\nand another line\nand a third one\n"   # far from live
    w = _world(tmp_path, history=(V0, V1, V2))
    item = _plan_item(w, tmp_path)
    text = merge.render_dossier(item)
    by_sha = {c.sha: c for c in item.candidates}
    others = sorted((c for c in item.candidates if c.sha != merge._base_sha7(item)),
                    key=lambda c: c.score)
    assert len(others) == 2 and others[0].score < others[1].score
    listing = text.split("Other versions of this file")[1]
    assert listing.index(others[0].sha) < listing.index(others[1].sha)


def test_render_dossier_lists_others_nearest_first_and_never_the_base(tmp_path):
    """Mutation survivors N9/N10 (round 2): the base is not one of the
    'other versions', and the others are ordered by distance, not by the
    order git listed them."""
    from dazzle_claude_config.manifest import Entry
    entry = Entry(repo="dotclaude/x", territory="dotclaude", target="x", strategy="copy")
    base = tmp_path / "x.head.base-base000"
    item = merge.MergeItem(entry=entry, rel="", live=tmp_path / "l", repo=tmp_path / "r", base=base)
    item.candidates = [
        merge.Candidate("far0000", "2026-01-01", 9, False, False),     # listed first by git
        merge.Candidate("base000", "2026-02-02", 0, False, False),     # the base
        merge.Candidate("near000", "2026-03-03", 1, False, True),
    ]
    item.checkout_state = "committed"
    text = merge.render_dossier(item)
    listing = text.split("Other versions of this file")[1].split("\n")[0]
    assert "base000" not in listing
    assert listing.index("near000") < listing.index("far0000")


def test_hints_keep_their_prefix(tmp_path, monkeypatch):
    """Mutation survivor N8: the hints the terminal prints are marked as
    hints in the prompt too, so the model knows their rank."""
    w = _world(tmp_path)
    item = _plan_item(w, tmp_path)
    monkeypatch.setattr(merge, "resolution_hints",
                        lambda i: ["prefer the payload's copy: yours carries a regressed pattern"])
    text = merge.render_dossier(item)
    assert "Hint: prefer the payload's copy" in text


def test_a_half_known_remote_position_is_still_reported(tmp_path):
    """Mutation survivor M14: `ahead_behind` may know one side only."""
    w = _world(tmp_path)
    item = _plan_item(w, tmp_path)
    text = merge.render_dossier(item, remote=(2, None))
    assert "2 commits ahead" in text and "0 behind" in text and "unknown (no fetch" not in text


# -- the words -----------------------------------------------------------------

def test_render_dossier_says_the_base_the_candidates_the_tree_and_the_remote(tmp_path):
    w = _world(tmp_path)
    item = _plan_item(w, tmp_path)
    text = merge.render_dossier(item, remote=(2, 1), live=livegit.LiveGit(None, False, []))
    assert "The base ccs chose:" in text and "(inferred)" in text and "committed 20" in text
    assert "Other versions of this file in the checkout's history" in text
    assert "weak ranking" in text
    assert "equals the payload's copy" in text
    assert "The payload's copy in the checkout is committed" in text
    assert "2 commits ahead" in text and "1 behind" in text
    assert "not tracked by any git repository" in text


def test_render_dossier_names_an_uncommitted_edit_and_a_tracked_live_file(tmp_path):
    w = _world(tmp_path)
    (w["co"] / "dotclaude" / "skills" / "s.md").write_bytes(V2 + b"x\n")
    item = _plan_item(w, tmp_path)
    lg = livegit.LiveGit(tmp_path / "home", True, [("abc1234", "2026-09-01"), ("def5678", "2026-08-20")])
    text = merge.render_dossier(item, remote=None, live=lg)
    assert "UNCOMMITTED edit" in text and "modified" in text
    assert "abc1234 2026-09-01" in text and "recent commits" in text
    assert "remote" in text.lower() and "unknown" in text.lower()


def test_render_dossier_marks_a_search_that_stopped_early(tmp_path):
    w = _world(tmp_path, live=V1)
    item = _plan_item(w, tmp_path) if False else None
    # plan() skips a live file equal to a commit only when it equals HEAD; V1 != HEAD, so plan it
    manifest = Manifest.load(w["co"])
    roots = {"CLAUDE_DIR": w["live"], "USER_CLAUDE": w["user"]}
    items = merge.plan(manifest, w["co"], roots, stage=tmp_path / "stage")
    item = next(i for i in items if i.label == "skills/s.md")
    text = merge.render_dossier(item)
    assert "stopped" in text and "equals your live file" in text


def test_dossier_facts_are_structured_and_exclude_the_remote(tmp_path):
    w = _world(tmp_path)
    item = _plan_item(w, tmp_path)
    facts = merge.dossier_facts(item, live=livegit.LiveGit(tmp_path, True, [("abc1234", "2026-09-01")]))
    assert facts["checkout_state"] == "committed"
    assert facts["live_tracked"] is True and facts["live_head"] == "abc1234"
    assert "remote" not in " ".join(facts) and all(isinstance(v, (str, bool, int)) for v in facts.values())
    json.dumps(facts)                                  # it must be hashable into the key


# -- the live probe --------------------------------------------------------------

def _state(repo: Path) -> str:
    return hashlib.sha256((_git(repo, "rev-parse", "HEAD") + _git(repo, "status", "--porcelain")
                           + _git(repo, "ls-files", "-s")).encode()).hexdigest()


def test_probe_reads_a_tracked_files_recent_commits(tmp_path):
    repo = tmp_path / "home"
    (repo / "sub").mkdir(parents=True)
    sp.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    f = repo / "sub" / "x.md"
    f.write_text("one\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "first")
    before = _state(repo)
    lg = livegit.probe(f)
    assert lg.toplevel == repo.resolve() and lg.tracked is True
    assert len(lg.recent) == 1 and len(lg.recent[0][0]) >= 7 and lg.recent[0][1].startswith("20")
    assert _state(repo) == before                    # read-only, proven on the state


def test_probe_says_untracked_and_not_a_repo(tmp_path):
    repo = tmp_path / "home"
    repo.mkdir()
    sp.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    loose = repo / "loose.md"
    loose.write_text("x\n", encoding="utf-8")
    lg = livegit.probe(loose)
    assert lg.toplevel == repo.resolve() and lg.tracked is False and lg.recent == []


def test_probe_outside_any_repository_says_so(tmp_path, monkeypatch):
    """On this box every path under the profile resolves to the HOME repo
    (the consultation's M4), so "no repository" is answered by git, faked:
    rev-parse fails, and the probe stops there."""
    monkeypatch.setattr(livegit, "_run", lambda args, cwd: (128, ""))
    outside = tmp_path / "y.md"
    outside.write_text("y\n", encoding="utf-8")
    lg2 = livegit.probe(outside)
    assert lg2.toplevel is None and lg2.tracked is False and lg2.recent == []


def test_probe_only_ever_runs_read_verbs(tmp_path, monkeypatch):
    """The module's whole invariant, pinned: no git verb that can write."""
    repo = tmp_path / "home"
    repo.mkdir()
    sp.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    f = repo / "a.md"
    f.write_text("a\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "a")
    # the spy goes in AFTER the fixture's own git calls: it patches the one
    # subprocess module every caller shares
    seen: list[list[str]] = []
    real = livegit.subprocess.run

    def spy(args, *a, **k):
        seen.append(list(args))
        return real(args, *a, **k)
    monkeypatch.setattr(livegit.subprocess, "run", spy)
    livegit.probe(f)
    assert seen, "the probe ran git"
    for argv in seen:
        assert argv[0] == "git" and argv[1] == "-C", argv
        verb = argv[3]                                   # git -C <cwd> <verb> ...
        assert verb in livegit.READ_VERBS, argv


def test_the_allowlist_is_exactly_the_three_read_verbs():
    """Mutation survivor M17: the allowlist is the invariant; a write verb
    slipping into it would make the spy test prove nothing."""
    assert livegit.READ_VERBS == ("rev-parse", "ls-files", "log")


def test_probe_returns_at_most_the_limit(tmp_path):
    """Mutation survivor M21: `-n <limit>` is passed; a long history is not
    read whole."""
    repo = tmp_path / "home"
    repo.mkdir()
    sp.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    f = repo / "a.md"
    for k in range(7):
        f.write_text(f"v{k}\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", f"v{k}")
    assert len(livegit.probe(f).recent) == 5
    assert len(livegit.probe(f, limit=2).recent) == 2


def test_describe_live_reads_as_a_sentence():
    assert "not tracked" in livegit.describe(livegit.LiveGit(None, False, []))
    assert "no commits" in livegit.describe(livegit.LiveGit(Path("r"), True, []))
    assert "abc1234 2026-09-01" in livegit.describe(livegit.LiveGit(Path("r"), True, [("abc1234", "2026-09-01")]))


# -- the prompt carries it -------------------------------------------------------

def test_the_prompt_carries_the_dossier(tmp_path, capsys):
    w = _world(tmp_path)
    main(_ccs(w, "merge", "skills/s.md", "--ai", "prompt-only", "--no-launch"))
    capsys.readouterr()
    prompt = next((w["user"] / "ccs-merge-rules" / "_prompts").glob("skills__s.md-*.md"))
    text = prompt.read_text(encoding="utf-8")
    assert "The base ccs chose:" in text
    assert "Other versions of this file" in text
    assert "The payload's copy in the checkout is committed" in text
    assert "(no ancestry evidence" not in text
