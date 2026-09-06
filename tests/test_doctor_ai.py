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


class _FakeCli:
    """A fake transport under "cli": doctor builds the real preset and asks
    it; only the executable lookup is faked."""

    def __init__(self, ready, warning=""):
        self._ready, self._warning = ready, warning

    def probe(self, spec):
        from dazzle_claude_config._vendor.ailib.types import Readiness
        return (Readiness(True, "its CLI was found: C:/fake/claude.exe", self._warning) if self._ready
                else Readiness(False, f"{spec.command[0]} is not on PATH"))

    def invoke(self, spec, req):
        raise AssertionError("doctor must never invoke")

    def capabilities(self, spec):
        return frozenset({"model", "stream"})


def _fake_cli(monkeypatch, ready, warning=""):
    from dazzle_claude_config._vendor.ailib import backend as _bm
    _bm.transport_for("cli")
    monkeypatch.setitem(_bm._TRANSPORTS, "cli", _FakeCli(ready, warning))


def test_doctor_warns_when_the_configured_backend_has_no_cli(tmp_path, capsys, monkeypatch):
    w = _world(tmp_path)
    (w["user"] / "ccs-config.json").write_text(json.dumps({"ai_merge_backend": "codex"}), encoding="utf-8")
    _fake_cli(monkeypatch, ready=False)
    out = _doctor(w, capsys)
    assert "ai merge backend codex" in out and "not on PATH" in out and "prompt-only" in out, out


def test_doctor_reports_a_backend_whose_cli_is_present(tmp_path, capsys, monkeypatch):
    w = _world(tmp_path)
    (w["user"] / "ccs-config.json").write_text(json.dumps({"ai_merge_backend": "claude"}), encoding="utf-8")
    _fake_cli(monkeypatch, ready=True)
    out = _doctor(w, capsys)
    assert "ai merge backend claude" in out and "found" in out, out
    assert "goes to a hosted model" in out                  # the CLI presets are off-prem


def test_doctor_names_the_missing_key_for_a_hosted_preset(tmp_path, capsys, monkeypatch):
    """A hosted provider with no key is the likeliest first-run failure; the
    sentence names the VARIABLE, never asks for the value."""
    w = _world(tmp_path)
    (w["user"] / "ccs-config.json").write_text(json.dumps({"ai_merge_backend": "openrouter"}), encoding="utf-8")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    out = _doctor(w, capsys)
    assert "ai merge backend openrouter" in out and "OPENROUTER_API_KEY" in out and "not set" in out, out


def test_doctor_warns_when_the_model_setting_cannot_be_honoured(tmp_path, capsys, monkeypatch):
    """Driven by the backend's capabilities, not by a table in the facade."""
    from dazzle_claude_config._vendor.ailib import backend as _bm
    from dazzle_claude_config._vendor.ailib.types import Readiness

    class _NoModel(_FakeCli):
        def capabilities(self, spec):
            return frozenset({"stream"})

    w = _world(tmp_path)
    (w["user"] / "ccs-config.json").write_text(
        json.dumps({"ai_merge_backend": "claude", "ai_merge_model": "opus-x"}), encoding="utf-8")
    _bm.transport_for("cli")
    monkeypatch.setitem(_bm._TRANSPORTS, "cli", _NoModel(ready=True))
    out = _doctor(w, capsys)
    assert "ai_merge_model is 'opus-x'" in out and "cannot be told" in out, out


def test_doctor_prints_a_window_warning_on_its_own_line(tmp_path, capsys, monkeypatch):
    w = _world(tmp_path)
    (w["user"] / "ccs-config.json").write_text(json.dumps({"ai_merge_backend": "claude"}), encoding="utf-8")
    _fake_cli(monkeypatch, ready=True, warning="loaded with a 197,120-token context")
    out = _doctor(w, capsys)
    assert "197,120-token context" in out


def test_a_broken_library_plus_a_model_setting_is_a_warning_not_a_traceback(tmp_path, capsys, monkeypatch):
    """U0 (2026-09-05). The try/except around the AI block exists to survive
    a missing or broken vendored copy -- and the ai_merge_model warning that
    followed it read `_backend` and `_names`, which are bound only inside
    the try. With the library broken AND a model set, doctor raised
    NameError: the one configuration where the person most needs a sentence
    got a traceback instead. Found by the refactor-advisor, verified by hand."""
    import sys
    import dazzle_claude_config
    w = _world(tmp_path)
    (w["user"] / "ccs-config.json").write_text(
        json.dumps({"ai_merge_backend": "claude", "ai_merge_model": "some-model"}), encoding="utf-8")
    # `from . import ailib` resolves through the package attribute when the
    # module is already imported (this file imports it), so both the attribute
    # and the sys.modules entry have to go for the import to raise.
    monkeypatch.delattr(dazzle_claude_config, "ailib", raising=False)
    monkeypatch.setitem(sys.modules, "dazzle_claude_config.ailib", None)
    out = _doctor(w, capsys)
    assert "ai merge library" in out and "missing or broken" in out, out


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


def test_ccs_starts_and_doctor_warns_when_the_vendored_copy_cannot_be_imported(tmp_path):
    """The checklist sweep of 2026-09-05 (run-02, step 2.5): the test above
    fakes a broken copy INSIDE a process where cli had already imported
    cleanly, which is not the failure a person meets. In reality the copy is
    imported when ccs starts -- cli -> merge -> aistep -> ailib -> _vendor --
    so a broken or missing copy killed every verb with a traceback before an
    argument was parsed, and doctor's warning could never run. A fresh
    interpreter with the vendored package made unimportable is the honest
    reproduction: ccs must start, doctor must print the warning, and no
    traceback may appear.

    Predicted before the fix: FAILS -- ImportError at `from
    dazzle_claude_config.cli import main`."""
    import subprocess
    import sys
    from pathlib import Path
    w = _world(tmp_path)
    (w["user"] / "ccs-config.json").write_text(
        json.dumps({"ai_merge_backend": "claude", "ai_merge_model": "some-model"}), encoding="utf-8")
    argv = _ccs(w, "doctor")
    code = (
        "import sys, json\n"
        "sys.modules['dazzle_claude_config._vendor.ailib'] = None\n"      # any import of it raises
        "from dazzle_claude_config.cli import main\n"
        f"sys.exit(main(json.loads({json.dumps(json.dumps(argv))})))\n")
    p = subprocess.run([sys.executable, "-c", code], cwd=str(Path(__file__).resolve().parents[1]),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert "Traceback" not in p.stderr, p.stderr
    assert "ai merge library" in p.stdout and "missing or broken" in p.stdout, p.stdout + p.stderr
    # doctor's own verdict line, and its own exit code: 1 means "usable, with
    # things worth fixing" -- a warning, which this is. Never a crash (>= 2).
    assert "doctor:" in p.stdout and p.returncode in (0, 1), (p.returncode, p.stdout[-800:], p.stderr[-800:])


def test_the_two_spellings_of_prompt_only_are_one():
    """`aistep.PROMPT_ONLY` is the caller's mode; `ailib.PROMPT_ONLY` is the
    presets' refusal of it. Two literals so `aistep` never imports the
    library at module scope (the test above); this pins them equal."""
    from dazzle_claude_config import aistep
    assert aistep.PROMPT_ONLY == ailib.PROMPT_ONLY == "prompt-only"
