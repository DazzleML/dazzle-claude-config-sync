"""`ccs merge|collect|apply <path>` -- one file, named the way `ccs diff` takes it.

Found 2026-09-02: `ccs merge skills/think/SKILL.md` errored with *unrecognized
arguments* because only `--only` existed, while `ccs diff think/SKILL.md`
worked. The two resolve differently -- `--only` matches the repo-side label
component-wise, `diff` resolves a whole-component suffix and lists ambiguity
-- so the positional must resolve as `diff` does and hand the verb the
qualified repo label as its `--only` scope. A bare alias would have kept the
inconsistency.
"""
from __future__ import annotations

import subprocess as sp
from types import SimpleNamespace

import pytest

from dazzle_claude_config import boxconfig
from dazzle_claude_config.cli import _fold_path_into_only, main
from dazzle_claude_config.manifest import Manifest

from conftest import GIT_ID


def _git(co, *args: str) -> str:
    r = sp.run(["git", *GIT_ID, "-C", str(co), *args], capture_output=True, text=True)
    assert r.returncode == 0, f"git {args}: {r.stderr}"
    return r.stdout


@pytest.fixture
def world(tmp_path):
    """Two directory entries, `s/` and `t/`, each holding SAME.md, plus a
    single-file entry -- so a bare `SAME.md` is ambiguous, `t/SAME.md` is
    not, and `think/SKILL.md` reaches inside `skills`. Live edits every file
    so the differing set contains them."""
    co = tmp_path / "checkout"
    for d in ("s", "t", "skills/think"):
        (co / "dotclaude" / d).mkdir(parents=True)
    live = tmp_path / "live"
    for d in ("s", "t", "skills/think"):
        (live / d).mkdir(parents=True)
    user = tmp_path / "user"
    user.mkdir()
    sp.run(["git", "init", "-q", "-b", "main", str(co)], check=True)
    (co / "ccs-manifest.json").write_text(
        '{"manifest_version":1,'
        '"territories":{"dotclaude":{"root_var":"CLAUDE_DIR","repo_dir":"dotclaude"}},'
        '"entries":['
        '{"repo":"dotclaude/s","territory":"dotclaude","target":"s","strategy":"copy"},'
        '{"repo":"dotclaude/t","territory":"dotclaude","target":"t","strategy":"copy"},'
        '{"repo":"dotclaude/skills","territory":"dotclaude","target":"skills","strategy":"copy"},'
        '{"repo":"dotclaude/SEED.md","territory":"dotclaude","target":"SEED.md",'
        '"strategy":"seed-if-absent"},'
        '{"repo":"dotclaude/gpu.md","territory":"dotclaude","target":"gpu.md",'
        '"strategy":"copy","tags":["gpu"]}'
        ']}', encoding="utf-8")
    for rel in ("s/SAME.md", "t/SAME.md", "skills/think/SKILL.md", "SEED.md", "gpu.md"):
        (co / "dotclaude" / rel).write_text(f"{rel} checkout\n", encoding="utf-8")
    _git(co, "add", "-A"); _git(co, "commit", "-qm", "seed")
    for rel in ("s/SAME.md", "t/SAME.md", "skills/think/SKILL.md", "SEED.md", "gpu.md"):
        (live / rel).write_text(f"{rel} live edit\n", encoding="utf-8")
    return co, live, user


def _argv(co, live, user, *rest):
    return ["--checkout-dir", str(co), "--claude-dir", str(live),
            "--user-claude", str(user), "--no-color", "--no-fetch", *rest]


def _fold(co, live, user, verb, path, only=None):
    """Drive the resolver the way main() does, and return the scope it set."""
    manifest = Manifest.load(co)
    roots = {"CLAUDE_DIR": live, "USER_CLAUDE": user}
    args = SimpleNamespace(verb=verb, path=path, only=only)
    rc = _fold_path_into_only(args, manifest, co, roots, boxconfig.load(user))
    return rc, args.only


# -- resolution --------------------------------------------------------------

@pytest.mark.parametrize("verb", ["merge", "collect", "apply"])
def test_a_suffix_resolves_to_the_qualified_repo_label(world, verb):
    co, live, user = world
    rc, only = _fold(co, live, user, verb, "think/SKILL.md")
    assert rc is None
    assert only == "dotclaude/skills/think/SKILL.md"


def test_a_qualified_path_disambiguates(world):
    co, live, user = world
    rc, only = _fold(co, live, user, "merge", "t/SAME.md")
    assert rc is None and only == "dotclaude/t/SAME.md"


def test_backslashes_and_a_leading_slash_are_tolerated(world):
    co, live, user = world
    rc, only = _fold(co, live, user, "apply", "\\think\\SKILL.md")
    assert rc is None and only == "dotclaude/skills/think/SKILL.md"


def test_a_seed_entry_is_reachable_through_the_manifest(world):
    """diff_all walks copy entries only, so the file-level resolver never sees
    a seed-if-absent entry -- yet that is the very file merge's seed refusal
    tells you to name. The fold falls back to the manifest for it."""
    co, live, user = world
    rc, only = _fold(co, live, user, "merge", "SEED.md")
    assert rc is None and only == "dotclaude/SEED.md"


def test_diff_resolves_a_seed_entry_too(world, capsys):
    """For one release `ccs merge SEED.md` resolved and `ccs diff SEED.md` did
    not: the manifest fallback lived in the positional's caller. It is the
    resolver's last step now, so the verb that takes a path first gets it."""
    co, live, user = world
    rc = main(_argv(co, live, user, "diff", "SEED.md"))
    out, err = capsys.readouterr()
    assert rc in (0, 1), (out, err)
    assert "no such file" not in err
    assert "SEED.md live edit" in out          # the diff body was printed


def test_one_path_resolves_to_one_label_for_all_four_verbs(world):
    """`_resolve_pair` with the manifest step is what every path-taking verb
    reads; the three folds must agree with it, and with each other."""
    from dazzle_claude_config.cli import _resolve_pair
    from dazzle_claude_config.syncmap import diff_all
    co, live, user = world
    manifest = Manifest.load(co)
    roots = {"CLAUDE_DIR": live, "USER_CLAUDE": user}
    direct = _resolve_pair(diff_all(manifest, co, roots), "SEED.md",
                           manifest=manifest, checkout=co, roots=roots)
    assert direct is not None and direct[3] == "dotclaude/SEED.md"
    for verb in ("merge", "collect", "apply"):
        rc, only = _fold(co, live, user, verb, "SEED.md")
        assert rc is None and only == direct[3], verb


def test_a_tag_gated_file_named_at_merge_says_not_for_this_box(world, capsys):
    """A typo and a missing tag must not print the same words -- `diff` has
    said "not for this box" since the gate existed; the positional says it
    too, from the same function."""
    co, live, user = world                     # the box declares no tags
    rc = main(_argv(co, live, user, "merge", "--dry-run", "--no-launch", "gpu.md"))
    _out, err = capsys.readouterr()
    assert rc == 2
    assert "not for this box" in err and "needs" in err and "gpu" in err


def test_the_not_found_sentence_is_defined_once():
    """One condition, one sentence (#39's rule): the source carries the
    string exactly once, in the helper both `diff` and the positional call."""
    from pathlib import Path
    import dazzle_claude_config.cli as cli
    src = Path(cli.__file__).read_text(encoding="utf-8")
    assert src.count("no such file in any manifest entry") == 1
    assert src.count("in the manifest or the checkout") == 0   # the second wording is gone


def test_diff_is_untouched_by_the_fold(world):
    """`diff` has its own positional and its own handling; the fold must not
    turn it into a --only scope diff does not read."""
    co, live, user = world
    rc, only = _fold(co, live, user, "diff", "t/SAME.md")
    assert rc is None and only is None


# -- refusals, each with the reason on stderr ---------------------------------

def test_ambiguity_is_listed_never_guessed(world, capsys):
    co, live, user = world
    rc = main(_argv(co, live, user, "merge", "--dry-run", "--no-launch", "SAME.md"))
    _out, err = capsys.readouterr()
    assert rc == 2, err
    assert "ambiguous" in err and "2 files" in err
    assert "dotclaude/s/SAME.md" in err and "dotclaude/t/SAME.md" in err


def test_unknown_file_is_an_error_not_a_silent_empty_run(world, capsys):
    co, live, user = world
    rc = main(_argv(co, live, user, "apply", "--dry-run", "nope/NOPE.md"))
    _out, err = capsys.readouterr()
    assert rc == 2 and "no such file" in err


def test_both_forms_at_once_is_refused(world, capsys):
    co, live, user = world
    rc = main(_argv(co, live, user, "collect", "--dry-run",
                    "--only", "dotclaude/t", "t/SAME.md"))
    _out, err = capsys.readouterr()
    assert rc == 2 and "not both" in err


# -- end to end: the scope actually narrows the verb --------------------------

def test_collect_dry_run_is_scoped_to_the_named_file(world, capsys):
    co, live, user = world
    rc = main(_argv(co, live, user, "collect", "--dry-run", "t/SAME.md"))
    out, err = capsys.readouterr()
    assert rc in (0, 1), (out, err)
    assert "t/SAME.md" in out
    assert "s/SAME.md" not in out and "SKILL.md" not in out


def test_merge_dry_run_is_scoped_to_the_named_file(world, capsys):
    co, live, user = world
    rc = main(_argv(co, live, user, "merge", "--dry-run", "--no-launch",
                    "think/SKILL.md"))
    out, err = capsys.readouterr()
    assert rc in (0, 1), (out, err)
    assert "SKILL.md" in out
    assert "SAME.md" not in out


# -- #56: three outcomes, not two -------------------------------------------

def test_a_filter_that_matched_nothing_does_not_claim_the_sides_agree(world, capsys):
    """`--only X` matching no entry compared NOTHING, so the reassuring
    sentence is not merely unhelpful, it is false -- and it printed directly
    under a warning saying the opposite. Reported from a real run whose
    CCS_CHECKOUT_DIR still pointed at a scratch world."""
    co, live, user = world
    rc = main(_argv(co, live, user, "apply", "--dry-run", "--only", "dotclaude/nope"))
    out = capsys.readouterr().out
    assert "matched no manifest entries" in out            # the warning, as before
    assert "matched no manifest entry, so nothing was compared" in out
    assert "already matches the checkout" not in out, out
    assert rc == 0


def test_a_filter_that_matched_nothing_names_the_other_verb_when_the_path_is_there(world, capsys):
    """apply and collect are the same operation in opposite directions, and
    naming the wrong one is the easiest mistake here. When the unmatched
    label DOES exist on the live side, say so and name `collect`."""
    co, live, user = world
    (live / "notes").mkdir()
    (live / "notes" / "own.md").write_text("mine\n", encoding="utf-8")
    rc = main(_argv(co, live, user, "apply", "--dry-run", "--only", "dotclaude/notes"))
    out = capsys.readouterr().out
    assert "nothing was compared" in out
    assert "DOES exist" in out and "ccs collect" in out, out
    assert rc == 0


def test_the_in_sync_sentence_survives_where_it_is_true(world, capsys):
    """The guard on the change: a scope that matched and found the two sides
    identical must still get the reassuring line, or the fix has traded one
    wrong summary for another."""
    co, live, user = world
    (live / "t" / "SAME.md").write_text("t/SAME.md checkout\n", encoding="utf-8")
    rc = main(_argv(co, live, user, "apply", "--dry-run", "--only", "dotclaude/t"))
    out = capsys.readouterr().out
    assert "already matches the checkout" in out, out
    assert "nothing was compared" not in out
    assert rc == 0


def test_collect_gets_the_mirror(world, capsys):
    """The same three outcomes, pointing the other way."""
    co, live, user = world
    rc = main(_argv(co, live, user, "collect", "--dry-run", "--only", "dotclaude/nope"))
    out = capsys.readouterr().out
    assert "matched no manifest entry, so nothing was compared" in out
    assert "already has everything from your live config" not in out, out
    assert rc == 0
