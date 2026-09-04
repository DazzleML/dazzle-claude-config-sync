"""a6 -- what `ccs doctor` says about the AI merge.

Three lines: the backend `--ai` would use when the flag names none
(prompt-only, which sends nothing, is the default and an OK); a configured
backend whose CLI is not on PATH is a warning that names prompt-only as
the floor; and `ai_merge_command` -- documented since 0.3.0, never read --
set in a config file is a warning that points at `ai_merge_backend`.
"""
from __future__ import annotations

import json

from dazzle_claude_config import ailib
from dazzle_claude_config.cli import main

from test_merge_ai import _ccs, _world


def _doctor(w, capsys):
    main(_ccs(w, "doctor"))
    return capsys.readouterr().out


def test_doctor_says_prompt_only_is_in_effect_by_default(tmp_path, capsys):
    w = _world(tmp_path)
    out = _doctor(w, capsys)
    assert "ai merge: prompt-only" in out, out
    assert "no longer read" not in out


def test_doctor_warns_when_the_configured_backend_has_no_cli(tmp_path, capsys, monkeypatch):
    w = _world(tmp_path)
    (w["user"] / "ccs-config.json").write_text(json.dumps({"ai_merge_backend": "codex"}), encoding="utf-8")
    monkeypatch.setattr(ailib, "check_available", lambda name: False)
    out = _doctor(w, capsys)
    assert "ai merge backend codex" in out and "not on PATH" in out and "prompt-only" in out, out


def test_doctor_reports_a_backend_whose_cli_is_present(tmp_path, capsys, monkeypatch):
    w = _world(tmp_path)
    (w["user"] / "ccs-config.json").write_text(json.dumps({"ai_merge_backend": "claude"}), encoding="utf-8")
    monkeypatch.setattr(ailib, "check_available", lambda name: True)
    out = _doctor(w, capsys)
    assert "ai merge backend claude" in out and "found" in out, out


def test_an_explicit_null_backend_reads_as_prompt_only(tmp_path, capsys):
    """Mutation survivor cli-2: `cfg.get(...) or PROMPT_ONLY`. A config file
    that spells the key out as null means "unset", not a backend named
    "None" -- the doctor must not call the person's file invalid for it."""
    w = _world(tmp_path)
    (w["user"] / "ccs-config.json").write_text(json.dumps({"ai_merge_backend": None}), encoding="utf-8")
    out = _doctor(w, capsys)
    assert "ai merge: prompt-only" in out, out
    assert "not one of" not in out


def test_doctor_warns_that_ai_merge_command_is_no_longer_read(tmp_path, capsys):
    w = _world(tmp_path)
    (w["user"] / "ccs-config.json").write_text(
        json.dumps({"ai_merge_command": "my-merge-tool $CCS_BASE $CCS_OURS $CCS_OUT"}), encoding="utf-8")
    out = _doctor(w, capsys)
    assert "ai_merge_command" in out and "no longer read" in out and "ai_merge_backend" in out, out
