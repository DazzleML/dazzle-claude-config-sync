"""The `cli` transport: an executable, argv from a template, the prompt on
stdin. claude, codex, pi and gemini-cli are one transport with different
argv; nothing about a vendor lives in this file.

Against a real subprocess, not a mock: the fake CLI is a Python script the
test writes, which reports what it was actually given -- its stdin, its
argv, its working directory and its environment -- so the properties a
long-lived caller depends on (cwd and env handed to the CHILD, never set on
this process) are observed rather than assumed. One test does monkeypatch
`subprocess.run`, because the property "the parent's cwd and environ are
unchanged DURING the call" cannot be seen from outside the call.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from dazzle_claude_config._vendor.ailib.types import Request, Spec
from dazzle_claude_config._vendor.ailib.backend import build

FAKE_CLI = r'''
import json, os, sys, time
args = sys.argv[1:]
def opt(flag):
    return args[args.index(flag) + 1] if flag in args else None
if "--fail" in args:
    sys.stderr.write("boom: the fake refused\n"); sys.exit(3)
if "--slow" in args:
    time.sleep(5)
prompt = sys.stdin.read()
if "--stream" in args:
    for i in range(3):
        print(f"line {i}"); sys.stdout.flush(); time.sleep(0.05)
if "--banner" in args:
    print("Loading model..."); print("Ready.")
report = {
    "hunks": [{"hunk": 1, "lines": ["O1"], "rules": [], "rationale": "fake"}],
    "prompt_len": len(prompt),
    "model": opt("--model") or "",
    "cwd": os.getcwd(),
    "has_claudecode": "CLAUDECODE" in os.environ,
    "schema_arg": opt("--json-schema"),
    "schema_file": (os.path.isfile(opt("--output-schema")) if opt("--output-schema") else None),
    "argv": args,
}
if opt("--touch"):
    open(opt("--touch"), "w", encoding="utf-8").write("touched")     # relative to the child's cwd
report["allowed_tools"] = opt("--allowedTools")
out = opt("-o")
if out:
    open(out, "w", encoding="utf-8").write(json.dumps(report)); print("wrote the answer to a file")
elif "--envelope" in args:
    print(json.dumps({"type": "result", "result": "prose here", "structured_output": report}))
elif "--fence" in args:
    print("Some prose.\n```json\n" + json.dumps(report) + "\n```\n")
else:
    print(json.dumps(report))
'''

SCHEMA = {"type": "object", "properties": {"hunks": {"type": "array"}}, "required": ["hunks"]}


@pytest.fixture
def cli(tmp_path):
    script = tmp_path / "fake_cli.py"
    script.write_text(FAKE_CLI, encoding="utf-8")
    return script


def _spec(cli, *tail, **kw):
    return Spec("cli", name="fake", command=(sys.executable, str(cli), *tail), **kw)


def _report(resp):
    return json.loads(resp.text)


# -- finding the executable -------------------------------------------------------

def test_probe_finds_an_executable_and_says_so(cli):
    ready = build(_spec(cli)).probe()
    assert ready.ok and "found" in ready.reason


def test_probe_names_a_missing_executable(cli):
    ready = build(Spec("cli", command=("no-such-cli-anywhere", "-p"))).probe()
    assert ready.ok is False and "no-such-cli-anywhere" in ready.reason and "not on PATH" in ready.reason


def test_candidates_are_tried_after_path(cli, tmp_path):
    """codex's npm and WinGet shims, claude's ~/.local/bin: places PATH may
    not know. A candidate that exists is used by its full path."""
    exe = tmp_path / "hidden" / "thing.cmd"
    exe.parent.mkdir()
    exe.write_text("@echo off\n", encoding="utf-8")
    spec = Spec("cli", command=("thing-not-on-path",), candidates=(str(exe),))
    ready = build(spec).probe()
    assert ready.ok, ready.reason


# -- the request reaches the child -----------------------------------------------

def test_the_prompt_goes_on_stdin_whole(cli):
    prompt = "x" * 20000                                   # far past any argv limit
    r = build(_spec(cli)).invoke(Request(prompt=prompt, timeout=20))
    assert r.ok and _report(r)["prompt_len"] == 20000


def test_model_is_substituted_from_the_spec_and_honoured(cli):
    r = build(_spec(cli, "--model", "{model}", model="opus")).invoke(Request(prompt="p", timeout=20))
    assert _report(r)["model"] == "opus"
    assert "model" in r.honoured and r.model_used == "opus"


def test_an_empty_placeholder_drops_itself_and_its_flag(cli):
    """`--model {model}` with no model must not become `--model ""`."""
    r = build(_spec(cli, "--model", "{model}", "--marker")).invoke(Request(prompt="p", timeout=20))
    argv = _report(r)["argv"]
    assert "--model" not in argv and "" not in argv and "--marker" in argv
    assert "model" not in r.honoured


def test_an_inline_schema_placeholder_gets_the_schema_as_one_token(cli):
    r = build(_spec(cli, "--json-schema", "{schema}")).invoke(Request(prompt="p", schema=SCHEMA, timeout=20))
    assert json.loads(_report(r)["schema_arg"]) == SCHEMA
    assert "schema" in r.honoured


def test_a_schema_file_placeholder_materialises_the_file_in_the_scratch_dir(cli):
    r = build(_spec(cli, "--output-schema", "{schema_file}")).invoke(Request(prompt="p", schema=SCHEMA, timeout=20))
    assert _report(r)["schema_file"] is True
    assert "schema" in r.honoured


def test_no_schema_means_the_placeholder_is_dropped_and_schema_is_not_honoured(cli):
    r = build(_spec(cli, "--json-schema", "{schema}")).invoke(Request(prompt="p", timeout=20))
    assert _report(r)["schema_arg"] is None and "schema" not in r.honoured


# -- where the answer is ------------------------------------------------------------

def test_the_default_locator_is_stdout(cli):
    r = build(_spec(cli)).invoke(Request(prompt="p", timeout=20))
    assert r.ok and json.loads(r.text)["hunks"]


def test_a_json_envelope_locator_extracts_one_key(cli):
    """claude's --output-format json: an envelope whose `structured_output`
    holds the answer and whose `result` holds the prose."""
    r = build(_spec(cli, "--envelope", answer="stdout-json:structured_output")).invoke(Request(prompt="p", timeout=20))
    assert r.ok and json.loads(r.text)["hunks"]
    r2 = build(_spec(cli, "--envelope", answer="stdout-json:result")).invoke(Request(prompt="p", timeout=20))
    assert r2.text == "prose here"


def test_a_chatty_cli_puts_its_envelope_on_the_LAST_line(cli):
    """Sweep survivor m6: banner text before the JSON must not hide it."""
    r = build(_spec(cli, "--banner", "--envelope", answer="stdout-json:structured_output")).invoke(Request(prompt="p", timeout=20))
    assert r.ok and json.loads(r.text)["hunks"], r.error


def test_no_schema_means_a_schema_file_placeholder_is_dropped_too(cli):
    """Sweep survivor m10: with no schema, {schema_file} must not materialise
    a file containing `null` and keep its flag."""
    r = build(_spec(cli, "--output-schema", "{schema_file}")).invoke(Request(prompt="p", timeout=20))
    rep = _report(r)
    assert rep["schema_file"] is None and "--output-schema" not in rep["argv"]
    assert "schema" not in r.honoured


@pytest.mark.skipif(sys.platform != "win32", reason="a .CMD shim is a Windows thing")
def test_an_upper_case_cmd_shim_that_does_not_run_is_not_reported_ready(tmp_path):
    """Sweep survivor m8: the shim check must be case-blind; Windows is."""
    shim = tmp_path / "THING.CMD"
    shim.write_text("@exit /b 1\r\n", encoding="ascii")
    ready = build(Spec("cli", command=("thing-not-on-path",), candidates=(str(shim),))).probe()
    assert ready.ok is False and "does not run" in ready.reason


def test_a_missing_envelope_key_is_a_failure_with_the_keys_it_saw(cli):
    r = build(_spec(cli, "--envelope", answer="stdout-json:nope")).invoke(Request(prompt="p", timeout=20))
    assert r.status == "failed" and "nope" in r.error and "structured_output" in r.error


def test_a_file_locator_reads_the_output_file_from_the_scratch_dir(cli):
    """codex's -o FILE: the last message lands in a file, stdout is chatter."""
    r = build(_spec(cli, "-o", "{output_file}", answer="file:{output_file}")).invoke(Request(prompt="p", timeout=20))
    assert r.ok and json.loads(r.text)["hunks"]


# -- the child's world, not ours --------------------------------------------------

def test_env_unset_removes_variables_from_the_child_only(cli, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    r = build(_spec(cli, env_unset=("CLAUDECODE",))).invoke(Request(prompt="p", timeout=20))
    assert _report(r)["has_claudecode"] is False
    assert os.environ["CLAUDECODE"] == "1"                 # ours, untouched


def test_the_child_runs_in_a_scratch_dir_that_is_removed_afterwards(cli):
    r = build(_spec(cli)).invoke(Request(prompt="p", timeout=20))
    child_cwd = Path(_report(r)["cwd"])
    assert child_cwd != Path.cwd()
    assert str(child_cwd).startswith(str(Path(tempfile.gettempdir()).resolve())[:8]) or "ailib" in child_cwd.name
    assert not child_cwd.exists()


def test_our_cwd_and_environ_are_untouched_DURING_the_call(cli, monkeypatch):
    """Not before-and-after (today's facade restores both in `finally`, so
    that check cannot go red): at the moment the subprocess is started."""
    seen = {}
    real_run = subprocess.run

    def spy(*a, **kw):
        seen["cwd"], seen["env"] = os.getcwd(), dict(os.environ)
        return real_run(*a, **kw)

    monkeypatch.setattr(subprocess, "run", spy)
    before_cwd, before_env = os.getcwd(), dict(os.environ)
    build(_spec(cli)).invoke(Request(prompt="p", timeout=20))
    assert seen["cwd"] == before_cwd and seen["env"] == before_env


# -- a populated working directory, and the tools grant (U3 of #64, 2026-09-09) ------
#
# The deep merge runs a CLI INSIDE a sandbox copy it prepared, so the
# request may name a working directory: the child runs there, may write
# there, and the directory is the caller's to keep and read back -- the
# transport does not remove it. Only then does the `{tools}` placeholder
# take the preset's grant; without a workdir it vanishes with its flag, so
# pass 1's argv is byte-identical to before.

def test_a_workdir_on_the_request_is_the_childs_cwd_and_survives_the_call(cli, tmp_path):
    work = tmp_path / "sandbox"
    work.mkdir()
    r = build(_spec(cli, "--touch", "made-here.txt")).invoke(Request(prompt="p", timeout=20, workdir=str(work)))
    assert r.ok, r.error
    assert Path(_report(r)["cwd"]).resolve() == work.resolve()     # the child ran THERE
    assert (work / "made-here.txt").read_text(encoding="utf-8") == "touched"   # and what it wrote is kept
    assert work.is_dir()                                            # the directory is the caller's


def test_without_a_workdir_the_tools_placeholder_and_its_flag_vanish(cli):
    """Pass 1's argv must not change: a preset that carries a grant sends
    nothing of it when the request names no working directory."""
    r = build(_spec(cli, "--allowedTools", "{tools}", "--marker", tools="Read,Grep,Edit,Write")).invoke(
        Request(prompt="p", timeout=20))
    argv = _report(r)["argv"]
    assert "--allowedTools" not in argv and "{tools}" not in argv and "--marker" in argv
    assert "tools" not in r.honoured
    assert _report(r)["allowed_tools"] is None


def test_with_a_workdir_the_grant_is_substituted_and_honoured(cli, tmp_path):
    work = tmp_path / "sandbox"
    work.mkdir()
    r = build(_spec(cli, "--allowedTools", "{tools}", tools="Read,Grep,Edit,Write")).invoke(
        Request(prompt="p", timeout=20, workdir=str(work)))
    assert _report(r)["allowed_tools"] == "Read,Grep,Edit,Write"
    assert "tools" in r.honoured


def test_a_workdir_with_an_empty_grant_sends_no_flag_and_honours_nothing(cli, tmp_path):
    work = tmp_path / "sandbox"
    work.mkdir()
    r = build(_spec(cli, "--allowedTools", "{tools}")).invoke(Request(prompt="p", timeout=20, workdir=str(work)))
    assert _report(r)["allowed_tools"] is None and "tools" not in r.honoured


def test_the_scratch_files_are_still_made_when_the_child_runs_in_a_workdir(cli, tmp_path):
    """A schema file belongs to the call, not to the sandbox: it is written
    in the transport's own scratch (removed afterwards), while the child
    runs in the workdir and `{cwd}` names the workdir."""
    work = tmp_path / "sandbox"
    work.mkdir()
    r = build(_spec(cli, "--output-schema", "{schema_file}", "--marker", "{cwd}")).invoke(
        Request(prompt="p", schema=SCHEMA, timeout=20, workdir=str(work)))
    rep = _report(r)
    assert rep["schema_file"] is True and "schema" in r.honoured
    assert Path(rep["cwd"]).resolve() == work.resolve()
    assert Path(rep["argv"][rep["argv"].index("--marker") + 1]).resolve() == work.resolve()
    assert not list(work.iterdir())                                 # nothing of the transport's landed in the sandbox


def test_the_streaming_path_runs_the_child_in_the_workdir_too(cli, tmp_path):
    """v0.6.3 sweep, survivor cli-8: the streaming branch handed `_stream`
    the scratch instead of the workdir and nothing noticed, because every
    workdir test ran the non-streaming branch. `--ai-verbose` on a deep
    run must not quietly move the child out of the sandbox."""
    work = tmp_path / "sandbox"
    work.mkdir()
    sink = io.StringIO()
    r = build(_spec(cli, "--touch", "streamed.txt")).invoke(
        Request(prompt="p", timeout=20, workdir=str(work), stream_to=sink))
    assert r.ok, r.error
    assert "stream" in r.honoured
    assert Path(json.loads(r.text.strip().splitlines()[-1])["cwd"]).resolve() == work.resolve()
    assert (work / "streamed.txt").is_file()


def test_capabilities_say_tools_only_with_both_the_placeholder_and_a_grant(cli):
    assert "tools" in build(_spec(cli, "--allowedTools", "{tools}", tools="Read,Grep")).capabilities
    assert "tools" not in build(_spec(cli, "--allowedTools", "{tools}")).capabilities       # no grant
    assert "tools" not in build(_spec(cli, tools="Read,Grep")).capabilities                  # no placeholder


# -- failures with a sentence ---------------------------------------------------------

def test_a_nonzero_exit_is_a_failure_carrying_the_childs_stderr(cli):
    r = build(_spec(cli, "--fail")).invoke(Request(prompt="p", timeout=20))
    assert r.status == "failed" and "code 3" in r.error and "boom" in r.error


def test_a_timeout_is_a_failure_that_says_so(cli):
    r = build(_spec(cli, "--slow")).invoke(Request(prompt="p", timeout=1))
    assert r.status == "failed" and "timed out" in r.error


def test_a_missing_executable_fails_without_raising():
    r = build(Spec("cli", command=("no-such-cli-anywhere",))).invoke(Request(prompt="p", timeout=5))
    assert r.status == "failed" and "no-such-cli-anywhere" in r.error


# -- streaming ---------------------------------------------------------------------------

def test_stream_to_receives_the_childs_lines_as_they_come(cli):
    sink = io.StringIO()
    r = build(_spec(cli, "--stream")).invoke(Request(prompt="p", timeout=20, stream_to=sink))
    assert r.ok and "line 0" in sink.getvalue() and "line 2" in sink.getvalue()
    assert "stream" in r.honoured
    assert json.loads(r.text.strip().splitlines()[-1])["hunks"]     # the answer is still the text


# -- capabilities ------------------------------------------------------------------------

def test_capabilities_follow_the_template_and_the_preset(cli):
    plain = build(_spec(cli)).capabilities
    assert "stream" in plain and "model" not in plain and "schema" not in plain
    full = build(_spec(cli, "--model", "{model}", "--json-schema", "{schema}", model="m", on_prem=False)).capabilities
    assert {"model", "schema", "stream"} <= full and "data_stays_on_prem" not in full
    local = build(_spec(cli, on_prem=True)).capabilities
    assert "data_stays_on_prem" in local
