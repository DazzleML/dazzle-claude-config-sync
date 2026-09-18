"""K1 and K5 (2026-09-09) -- where a hosted backend's key comes from, end
to end, against the fake server and never a value in sight.

Three places, one order: a file named on purpose (`ai_merge_api_key_file`),
then the environment variable the preset names, then `~/claude/keys/
<preset>.env`. The maintainer's rule: "just as easy to block as it is to
include" -- a key in a file, in user territory, that a merge finds without
an export and that the payload never carries.

Every assertion here reads what the FAKE SERVER received (`_Fake.seen_auth`)
or greps for the value's ABSENCE; nothing prints a key.
"""
from __future__ import annotations

import json

from dazzle_claude_config import ailib, airecord
from dazzle_claude_config._vendor.ailib.backend import build
from dazzle_claude_config.cli import EXIT_CLEAN, main

from test_merge_ai import GOOD, PROPOSAL, _ccs, _world
from test_transport_openai_compat import _Fake, _ask, server   # noqa: F401  (the fixture, by name)

NAMED, ENV, KEYS = ("the-value-from-the-named-file", "the-value-from-the-environment",
                    "the-value-from-the-keys-directory")


def _keys_dir(root):
    keys = root / "keys"
    keys.mkdir(parents=True, exist_ok=True)
    return keys


def test_k5_read_order_on_the_fake_server(server, tmp_path, monkeypatch):
    """Three sources, three values, three runs -- and a fourth with nothing
    anywhere, whose sentence names all three places."""
    _Fake.native = False                                    # a hosted provider has no load state
    named = tmp_path / "named.env"
    named.write_text(f"OPENROUTER_API_KEY={NAMED}\n", encoding="utf-8")
    keys = _keys_dir(tmp_path / "user")
    (keys / "openrouter.env").write_text(f"OPENROUTER_API_KEY={KEYS}\n", encoding="utf-8")
    monkeypatch.setenv("OPENROUTER_API_KEY", ENV)

    def run(expected, **kw):
        _Fake.token = expected                              # the server accepts only this one
        r = _ask(build(ailib.spec_for("openrouter", endpoint=server.url, keys_dir=keys, **kw)))
        assert r.ok, r.error
        assert _Fake.seen_auth == f"Bearer {expected}"

    run(NAMED, api_key_file=str(named))                     # 1. the file named on purpose beats the environment
    run(ENV)                                                # 2. the environment beats the keys directory
    monkeypatch.delenv("OPENROUTER_API_KEY")
    run(KEYS)                                               # 3. the keys directory, last
    (keys / "openrouter.env").unlink()                      # 4. nothing anywhere
    ready = build(ailib.spec_for("openrouter", endpoint=server.url, keys_dir=keys)).probe()
    assert ready.ok is False
    assert "OPENROUTER_API_KEY" in ready.reason and "not set" in ready.reason
    assert str(keys / "openrouter.env") in ready.reason and "does not exist" in ready.reason


def test_k1_keys_dir_alone_reaches_the_model_and_the_value_appears_nowhere(server, tmp_path, capsys,
                                                                            monkeypatch):
    """`ccs merge --ai openrouter` with the variable unset and the key only
    in `~/claude/keys/openrouter.env`: the merge goes through, the record
    carries the ROUTE, and the value is in no output, record, proposal or
    cache file."""
    w = _world(tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("CCS_AI_MERGE_API_KEY_FILE", raising=False)
    (w["user"] / "ccs-config.json").write_text(json.dumps({"ai_merge_endpoint": server.url}),
                                               encoding="utf-8")
    (_keys_dir(w["user"]) / "openrouter.env").write_text(f"OPENROUTER_API_KEY={KEYS}\n", encoding="utf-8")
    _Fake.native = False
    _Fake.token = KEYS
    _Fake.content = json.dumps(GOOD)

    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "openrouter", "--no-launch"))
    captured = capsys.readouterr()
    assert rc == EXIT_CLEAN, captured.out
    assert _Fake.seen_auth == f"Bearer {KEYS}"              # the model was reached with the file's key
    assert airecord.proposal_path(w["merged"]).read_bytes() == PROPOSAL

    record_text = airecord.record_path(w["merged"]).read_text(encoding="utf-8")
    assert "keyfile:openrouter.env" in record_text          # the route is recorded...
    assert "key:OPENROUTER_API_KEY" in record_text
    everywhere = {"stdout": captured.out, "stderr": captured.err, "record": record_text}
    for p in list(w["ws"].rglob("*")) + list((w["user"] / "cache").rglob("*")):
        if p.is_file():
            everywhere[str(p)] = p.read_text(encoding="utf-8", errors="replace")
    assert len(everywhere) > 3, "the workspace and the cache should have files to check"
    for where, text in everywhere.items():
        assert KEYS not in text, where                      # ...and the value is nowhere


def test_k5_the_environment_variable_form_of_the_setting_reaches_the_merge(server, tmp_path, capsys,
                                                                            monkeypatch):
    """Mutation survivor M11 (v0.6.1 sweep): the setting's environment
    variable was misspelt in the table and nothing noticed, because every
    test set it in the config file. `CCS_AI_MERGE_API_KEY_FILE` alone must
    name the file."""
    w = _world(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", ENV)
    named = tmp_path / "elsewhere" / "mine.env"
    named.parent.mkdir()
    named.write_text(f"OPENROUTER_API_KEY={NAMED}\n", encoding="utf-8")
    monkeypatch.setenv("CCS_AI_MERGE_API_KEY_FILE", str(named))
    (w["user"] / "ccs-config.json").write_text(json.dumps({"ai_merge_endpoint": server.url}),
                                               encoding="utf-8")
    _Fake.native = False
    _Fake.token = NAMED
    _Fake.content = json.dumps(GOOD)
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "openrouter", "--no-launch"))
    out = capsys.readouterr().out
    assert rc == EXIT_CLEAN, out
    assert _Fake.seen_auth == f"Bearer {NAMED}"


def test_k5_the_config_key_reaches_the_merge(server, tmp_path, capsys, monkeypatch):
    """`ai_merge_api_key_file` in the config file is the named file, read
    before the environment."""
    w = _world(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", ENV)
    named = tmp_path / "elsewhere" / "mine.env"
    named.parent.mkdir()
    named.write_text(f"export OPENROUTER_API_KEY='{NAMED}'\n", encoding="utf-8")
    (w["user"] / "ccs-config.json").write_text(
        json.dumps({"ai_merge_endpoint": server.url, "ai_merge_api_key_file": str(named)}), encoding="utf-8")
    _Fake.native = False
    _Fake.token = NAMED
    _Fake.content = json.dumps(GOOD)
    rc = main(_ccs(w, "merge", "skills/s.md", "--ai", "openrouter", "--no-launch"))
    out = capsys.readouterr().out
    assert rc == EXIT_CLEAN, out
    assert _Fake.seen_auth == f"Bearer {NAMED}"
    assert NAMED not in out and ENV not in out
