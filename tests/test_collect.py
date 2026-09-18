"""collect: guard-stack behavior including A1 (refusals) and A8 (index check)."""
import dataclasses

from dazzle_claude_config.collect import collect
from dazzle_claude_config.gitops import CheckoutRepo


def test_clean_env_collects_nothing(env):
    _, _, checkout, manifest, roots = env
    r = collect(manifest, checkout, roots)
    assert r.copied == [] and r.refusals == 0


def test_new_and_modified_files_collected(env):
    claude, user, checkout, manifest, roots = env
    (claude / "agents" / "newbie.md").write_text("new agent\n", encoding="utf-8")
    (claude / "CLAUDE.md").write_text("# global memory v2\n", encoding="utf-8")
    r = collect(manifest, checkout, roots)
    assert "dotclaude/agents/newbie.md" in r.copied
    assert "dotclaude/CLAUDE.md" in r.copied
    assert (checkout / "dotclaude" / "agents" / "newbie.md").read_text(
        encoding="utf-8") == "new agent\n"
    assert (checkout / "dotclaude" / "CLAUDE.md").read_text(
        encoding="utf-8") == "# global memory v2\n"


def test_dry_run_copies_nothing(env):
    claude, _, checkout, manifest, roots = env
    (claude / "agents" / "newbie.md").write_text("new agent\n", encoding="utf-8")
    r = collect(manifest, checkout, roots, dry_run=True)
    assert "dotclaude/agents/newbie.md" in r.copied
    assert not (checkout / "dotclaude" / "agents" / "newbie.md").exists()


def test_only_scopes_collect_to_one_entry(env):
    """AC-1: --only must leave non-matching entries entirely untouched.

    Without this, the only way to publish part of a payload was to publish
    all of it -- which measured out at 13 personal files bound for a public
    repo (DWP-7 GT-6).
    """
    claude, _, checkout, manifest, roots = env
    (claude / "agents" / "newbie.md").write_text("new agent\n", encoding="utf-8")
    (claude / "CLAUDE.md").write_text("# global memory v2\n", encoding="utf-8")
    r = collect(manifest, checkout, roots, only="dotclaude/agents")
    assert "dotclaude/agents/newbie.md" in r.copied
    assert "dotclaude/CLAUDE.md" not in r.copied
    assert not (checkout / "dotclaude" / "CLAUDE.md").read_text(
        encoding="utf-8").startswith("# global memory v2")


def test_only_matching_nothing_is_reported_not_silent(env):
    """AC-2: a prefix that matches no entry must be visible, not a quiet 0.

    A typo'd --only otherwise reports success having copied nothing, which
    reads identically to 'already in sync'.
    """
    claude, _, checkout, manifest, roots = env
    (claude / "agents" / "newbie.md").write_text("new agent\n", encoding="utf-8")
    r = collect(manifest, checkout, roots, only="dotclaude/nope")
    assert r.only_matched == 0
    assert r.copied == []


def test_only_none_still_processes_every_entry(env):
    """AC-1 control: the default path must be unchanged by --only's addition."""
    claude, _, checkout, manifest, roots = env
    (claude / "agents" / "newbie.md").write_text("new agent\n", encoding="utf-8")
    (claude / "CLAUDE.md").write_text("# global memory v2\n", encoding="utf-8")
    r = collect(manifest, checkout, roots)
    assert r.only_matched > 1
    assert "dotclaude/agents/newbie.md" in r.copied
    assert "dotclaude/CLAUDE.md" in r.copied


def test_hold_additions_withholds_new_files(env):
    """AC-4: on a payload that declares hold_additions, a new live file is NOT
    copied and IS named.

    Measured motivation (DWP-7 GT-6): an unscoped collect toward the public
    payload would have published 13 personal files, and the only thing that
    stopped it was an unrelated CLAUDE.md refusal.
    """
    claude, _, checkout, manifest, roots = env
    strict = dataclasses.replace(manifest, hold_additions=True)
    (claude / "agents" / "personal-thing.md").write_text("private\n", encoding="utf-8")
    (claude / "CLAUDE.md").write_text("# global memory v2\n", encoding="utf-8")
    r = collect(strict, checkout, roots)
    assert "dotclaude/agents/personal-thing.md" in r.withheld_additions
    assert "dotclaude/agents/personal-thing.md" not in r.copied
    assert not (checkout / "dotclaude" / "agents" / "personal-thing.md").exists()
    # a file the checkout ALREADY tracks still updates -- gating additions must
    # not freeze the payload
    assert "dotclaude/CLAUDE.md" in r.copied


def test_hold_additions_add_flag_overrides(env):
    """AC-5: --add is the escape hatch, or the gate is a wall."""
    claude, _, checkout, manifest, roots = env
    strict = dataclasses.replace(manifest, hold_additions=True)
    (claude / "agents" / "wanted.md").write_text("share me\n", encoding="utf-8")
    r = collect(strict, checkout, roots, add=True)
    assert "dotclaude/agents/wanted.md" in r.copied
    assert r.withheld_additions == []


def test_hold_additions_permits_first_run_adoption(env, tmp_path):
    """AC-6: an entry the checkout carries nothing for is adoption, not drift.

    Without this, the FIRST collect against a fresh payload would withhold
    everything and report success -- a silent no-op (DWP-4: adoption creates
    the base).
    """
    claude, _, checkout, manifest, roots = env
    strict = dataclasses.replace(manifest, hold_additions=True)
    import shutil as _sh
    _sh.rmtree(checkout / "dotclaude" / "agents")
    (claude / "agents" / "first.md").write_text("first\n", encoding="utf-8")
    r = collect(strict, checkout, roots)
    assert "dotclaude/agents/first.md" in r.copied
    assert "dotclaude/agents" in r.adopted_entries


def test_hold_additions_defaults_off(env):
    """AC-11: a manifest without hold_additions behaves exactly as before.

    Both live payload repos predate this field; a default of True would have
    silently frozen them.
    """
    _, _, _, manifest, _ = env
    assert manifest.hold_additions is False


def test_a1_planted_secret_refused(env):
    claude, _, checkout, manifest, roots = env
    planted = "key = sk-ant-api03-" + "z" * 24 + "\n"
    (claude / "agents" / "leaky.md").write_text(planted, encoding="utf-8")
    r = collect(manifest, checkout, roots)
    assert len(r.refused_secrets) == 1
    assert r.refused_secrets[0].rel_path == "dotclaude/agents/leaky.md"
    assert not (checkout / "dotclaude" / "agents" / "leaky.md").exists()


def test_k2_openrouter_key_in_a_rules_file_is_refused(env):
    """K2 (#64): an OpenRouter key pasted into an ordinary collected file --
    the shape a person is now likeliest to have in their clipboard -- is
    refused at collect like an Anthropic one. Anchor: before the scan knew
    the shape this file was copied."""
    claude, _, checkout, manifest, roots = env
    (claude / "agents" / "rules.md").write_text(
        "prefer the payload\nkey: sk-or-v1-" + "0123456789abcdef" * 4 + "\n", encoding="utf-8")
    r = collect(manifest, checkout, roots)
    assert [h.rel_path for h in r.refused_secrets] == ["dotclaude/agents/rules.md"]
    assert r.refused_secrets[0].line_no == 2 and r.refused_secrets[0].excerpt.startswith("sk-or-v1-")
    assert not (checkout / "dotclaude" / "agents" / "rules.md").exists()


def _keys_manifest(checkout, *, allow: bool):
    import json
    from dazzle_claude_config.manifest import Manifest
    entry = {"repo": "userclaude/keys/openrouter.env", "territory": "userclaude",
             "target": "keys/openrouter.env", "strategy": "copy"}
    if allow:
        entry["allow_secrets"] = True
    (checkout / "ccs-manifest.json").write_text(json.dumps({
        "manifest_version": 1,
        "territories": {"userclaude": {"root_var": "USER_CLAUDE", "repo_dir": "userclaude"}},
        "entries": [entry]}), encoding="utf-8")
    (checkout / "userclaude" / "keys").mkdir(parents=True, exist_ok=True)
    return Manifest.load(checkout)


def test_k3_allowed_entry_collects_a_keys_file(env):
    """K3a (#64): one manifest line is how a person syncs a keys file on
    purpose -- `allow_secrets: true` on the entry skips the credential scan
    for it and reports the file as allowed. Anchor: without the allowance
    branch the same file is refused."""
    _, user, checkout, _, roots = env
    (user / "keys").mkdir()
    (user / "keys" / "openrouter.env").write_text(
        "OPENROUTER_API_KEY=sk-or-v1-" + "abcdef0123456789" * 4 + "\n", encoding="utf-8")
    manifest = _keys_manifest(checkout, allow=True)
    r = collect(manifest, checkout, roots)
    assert r.allowed_secrets == ["userclaude/keys/openrouter.env"]
    assert r.refused_secrets == []
    assert (checkout / "userclaude" / "keys" / "openrouter.env").read_text(encoding="utf-8").startswith("OPENROUTER_API_KEY=sk-or-v1-")


def test_k3_an_allowance_is_not_a_way_past_the_hard_deny(env):
    """Mutation survivor M7 (v0.6.1 sweep): a mutant that let an allowed
    entry skip the deny check at the copy loop survived, because every
    allowance test used a file no deny rule names. The comment at the
    branch says the deny list still applies; this is that sentence as a
    test, at the layer the branch lives: a SINGLE-FILE entry (the deny is
    checked on the file's own name there -- a directory entry's files are
    filtered earlier, in syncmap) naming a hard-denied file with
    `allow_secrets: true` is refused by name, never allowed, never copied."""
    import json
    from dazzle_claude_config.manifest import Manifest
    _, user, checkout, _, roots = env
    (user / ".credentials.json").write_text('{"token": "x"}', encoding="utf-8")
    (checkout / "ccs-manifest.json").write_text(json.dumps({
        "manifest_version": 1,
        "territories": {"userclaude": {"root_var": "USER_CLAUDE", "repo_dir": "userclaude"}},
        "entries": [{"repo": "userclaude/.credentials.json", "territory": "userclaude",
                     "target": ".credentials.json", "strategy": "copy", "allow_secrets": True}]}),
        encoding="utf-8")
    (checkout / "userclaude").mkdir(parents=True, exist_ok=True)
    r = collect(Manifest.load(checkout), checkout, roots)
    assert r.allowed_secrets == []
    assert [rel for rel, _ in r.refused_denied] == ["userclaude/.credentials.json"]
    assert not (checkout / "userclaude" / ".credentials.json").exists()


def test_k3_same_entry_without_the_allowance_is_refused(env):
    """K3b (#64): the same keys file under the same entry with no allowance
    is refused by the scan -- blocked is the default, including is the one
    line."""
    _, user, checkout, _, roots = env
    (user / "keys").mkdir()
    (user / "keys" / "openrouter.env").write_text(
        "OPENROUTER_API_KEY=sk-or-v1-" + "abcdef0123456789" * 4 + "\n", encoding="utf-8")
    manifest = _keys_manifest(checkout, allow=False)
    r = collect(manifest, checkout, roots)
    assert r.allowed_secrets == []
    assert [h.rel_path for h in r.refused_secrets] == ["userclaude/keys/openrouter.env"]
    assert not (checkout / "userclaude" / "keys" / "openrouter.env").exists()


def test_k3_the_allowed_line_prints_the_path_only(env, capsys):
    """K3a's report: `allowed <rel> -- allow_secrets on this entry: not
    scanned for credentials`, the path and never a line of the file; exit 0."""
    from dazzle_claude_config.cli import main
    claude, user, checkout, _, roots = env
    (user / "keys").mkdir()
    secret = "sk-or-v1-" + "fedcba9876543210" * 4
    (user / "keys" / "openrouter.env").write_text(f"OPENROUTER_API_KEY={secret}\n", encoding="utf-8")
    _keys_manifest(checkout, allow=True)
    rc = main(["--checkout-dir", str(checkout), "--claude-dir", str(claude), "--user-claude", str(user),
               "--no-color", "--no-fetch", "collect"])
    out = capsys.readouterr().out
    assert "allowed userclaude/keys/openrouter.env -- allow_secrets on this entry: not scanned for credentials" in out
    assert secret not in out and rc == 0


def test_a1_denied_filename_never_copied(env):
    """Deny-matched live files are annotated (denied_live), never copied,
    and -- per the v0.2.1 contract change (R6) -- are the guard WORKING,
    not an alarm: no nonzero exit for their mere presence."""
    claude, _, checkout, manifest, roots = env
    (claude / "agents" / ".credentials.json").write_text("{}", encoding="utf-8")
    (claude / "agents" / "notes.secret").write_text("shh", encoding="utf-8")
    r = collect(manifest, checkout, roots)
    assert "agents/.credentials.json" in r.denied_live
    assert "agents/notes.secret" in r.denied_live  # manifest deny extends hard deny
    assert not (checkout / "dotclaude" / "agents" / ".credentials.json").exists()
    assert not (checkout / "dotclaude" / "agents" / "notes.secret").exists()


def test_collect_exclude_honored(env):
    claude, _, checkout, manifest, roots = env
    pyc = claude / "agents" / "__pycache__"
    pyc.mkdir()
    (pyc / "junk.cpython-312.pyc").write_bytes(b"\x00")
    r = collect(manifest, checkout, roots)
    assert r.copied == []
    assert not (checkout / "dotclaude" / "agents" / "__pycache__").exists()


def test_exclusion_is_symmetric_repo_side(env):
    """Excluded files IN THE CHECKOUT (e.g. hook-generated __pycache__) are
    invisible to sync -- not phantom apply-pending drift."""
    from dazzle_claude_config.syncmap import diff_all
    _, _, checkout, manifest, roots = env
    pyc = checkout / "dotclaude" / "agents" / "__pycache__"
    pyc.mkdir()
    (pyc / "junk.cpython-312.pyc").write_bytes(b"\x00")
    assert all(d.clean for d in diff_all(manifest, checkout, roots))


def test_missing_live_reported_not_deleted(env):
    claude, _, checkout, manifest, roots = env
    (claude / "agents" / "oracle.md").unlink()
    r = collect(manifest, checkout, roots)
    assert "dotclaude/agents/oracle.md" in r.missing_live
    assert (checkout / "dotclaude" / "agents" / "oracle.md").exists()


def test_a8_git_ignored_copy_detected(env, monkeypatch):
    """A newly collected file swallowed by a machine-level exclude is flagged.

    (Tracked files are immune to excludes -- git check-ignore consults the
    index first -- so A8 specifically protects NEW files, matching the
    Phase 0 incident where an unanchored 'CLAUDE.md' in .git/info/exclude
    silently dropped a first-time file.)
    """
    claude, _, checkout, manifest, roots = env
    monkeypatch.setattr("dazzle_claude_config.gitops.Path.home",
                        staticmethod(lambda: checkout.parent / "nonexistent-home"))
    (checkout / ".git" / "info").mkdir(exist_ok=True)
    (checkout / ".git" / "info" / "exclude").write_text("newbie.md\n",
                                                        encoding="utf-8")
    (claude / "agents" / "newbie.md").write_text("new agent\n", encoding="utf-8")
    repo = CheckoutRepo(checkout)
    r = collect(manifest, checkout, roots, repo=repo)
    assert "dotclaude/agents/newbie.md" in r.copied
    assert "dotclaude/agents/newbie.md" in r.git_ignored
