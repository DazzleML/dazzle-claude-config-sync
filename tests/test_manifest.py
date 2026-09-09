import json

import pytest

from dazzle_claude_config.manifest import Manifest, ManifestError


def test_loads_valid_manifest(env):
    *_, manifest, _ = env
    assert manifest.version == 1
    assert len(manifest.copy_entries()) == 3
    assert len(manifest.seed_entries()) == 1
    assert [e.strategy for e in manifest.deferred_entries()] == ["render"]


def _write_manifest(checkout, data):
    (checkout / "ccs-manifest.json").write_text(json.dumps(data), encoding="utf-8")


def test_unknown_top_key_rejected(env):
    _, _, checkout, _, _ = env
    _write_manifest(checkout, {"manifest_version": 1, "territories": {},
                               "entries": [], "surprise": True})
    with pytest.raises(ManifestError, match="unknown manifest keys"):
        Manifest.load(checkout)


def test_bad_strategy_rejected(env):
    _, _, checkout, _, _ = env
    _write_manifest(checkout, {
        "manifest_version": 1,
        "territories": {"t": {"root_var": "CLAUDE_DIR", "repo_dir": "d"}},
        "entries": [{"repo": "d/x", "territory": "t", "target": "x",
                     "strategy": "symlink"}]})
    with pytest.raises(ManifestError, match="invalid strategy"):
        Manifest.load(checkout)


def test_wrong_version_rejected(env):
    _, _, checkout, _, _ = env
    _write_manifest(checkout, {"manifest_version": 99})
    with pytest.raises(ManifestError, match="unsupported manifest_version"):
        Manifest.load(checkout)


def test_missing_manifest_rejected(tmp_path):
    with pytest.raises(ManifestError, match="manifest not found"):
        Manifest.load(tmp_path)


def _one_entry_manifest(**extra):
    return {"manifest_version": 1,
            "territories": {"userclaude": {"root_var": "USER_CLAUDE", "repo_dir": "userclaude"}},
            "entries": [{"repo": "userclaude/keys/openrouter.env", "territory": "userclaude",
                         "target": "keys/openrouter.env", "strategy": "copy", **extra}]}


def test_allow_secrets_defaults_false(env):
    """K3 (#64): every pre-existing entry means "scan me"; the allowance is
    opt-in, per entry, and absent means False -- not None, not missing."""
    _, _, checkout, _, _ = env
    _write_manifest(checkout, _one_entry_manifest())
    entry = Manifest.load(checkout).entries[0]
    assert entry.allow_secrets is False


def test_allow_secrets_is_read_and_must_be_a_boolean(env):
    """K3 (#64): `allow_secrets: true` is read; `"true"` in quotes is refused
    with a sentence, the way an unknown `os` value is -- a value that parses
    and then means nothing would be a silent hole in the credential scan.
    Anchor: before the key existed, the first load failed on `unknown keys`."""
    _, _, checkout, _, _ = env
    _write_manifest(checkout, _one_entry_manifest(allow_secrets=True))
    assert Manifest.load(checkout).entries[0].allow_secrets is True
    _write_manifest(checkout, _one_entry_manifest(allow_secrets="true"))
    with pytest.raises(ManifestError, match="allow_secrets must be true or false"):
        Manifest.load(checkout)
