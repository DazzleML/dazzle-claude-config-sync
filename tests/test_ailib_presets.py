"""The presets: the named backends a person types after `--ai`, as DATA
over the library's transports. This is the line between what stays in ccs
and what generalises -- the library knows `cli`, `openai` and
`prompt-file`; ccs knows that `lmstudio` means the OpenAI transport at
127.0.0.1:1234 with reasoning turned off and a hint about the Developer
tab, that `openrouter` is the same transport at openrouter.ai with a key
named OPENROUTER_API_KEY, and that `claude` is the Claude Code CLI with two
environment variables scrubbed.

U2 of the seam rebuild (2026-09-05).
"""
from __future__ import annotations

import pytest

from dazzle_claude_config import ailib, userconfig
from dazzle_claude_config._vendor.ailib.backend import build


def test_every_preset_builds_and_probes_to_a_sentence(monkeypatch):
    for name in ailib.PRESETS:
        b = build(ailib.spec_for(name))
        ready = b.probe()                       # may be True or False on this box; must be a sentence
        assert isinstance(ready.reason, str) and ready.reason, name


def test_names_is_the_presets_plus_prompt_only_and_matches_the_config_choices():
    names = ailib.names()
    assert ailib.PROMPT_ONLY in names
    assert set(ailib.PRESETS) <= set(names)
    # the config layer duplicates the list ON PURPOSE (readable without the
    # AI machinery); doctor compares them, and so does this test
    assert set(names) == set(userconfig.KEYS["ai_merge_backend"].choices)


def test_prompt_only_is_a_mode_not_a_preset():
    assert ailib.PROMPT_ONLY not in ailib.PRESETS
    with pytest.raises(ValueError):
        ailib.spec_for(ailib.PROMPT_ONLY)


def test_an_unknown_name_is_refused_with_the_names():
    with pytest.raises(ValueError) as e:
        ailib.spec_for("gpt9")
    assert "gpt9" in str(e.value) and "lmstudio" in str(e.value)


# -- the four the north star names ----------------------------------------------

def test_claude_is_the_proven_argv_with_the_environment_scrubbed():
    s = ailib.spec_for("claude")
    assert s.transport == "cli" and s.command[0] == "claude"
    assert ("--output-format", "text") == tuple(s.command[1:3])
    assert s.command[-2:] == ("-p", "-")                     # the prompt on stdin
    assert "{model}" in " ".join(s.command)                   # --model when a model is set
    assert set(s.env_unset) == {"CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"}
    assert s.on_prem is False
    assert "model" in build(s).capabilities


def test_the_claude_presets_ask_for_opus_5_unless_told_otherwise():
    """The maintainer's word (2026-09-05): merges through the Claude Code CLI
    use Opus 5, not whatever model the CLI's session defaults to -- which is a
    different model a merge must not silently inherit. ai_merge_model still
    overrides; a preset default is not a lock."""
    from dazzle_claude_config._vendor.ailib.transports.cli import SubprocessCli
    from dazzle_claude_config._vendor.ailib.types import Request
    for name in ("claude", "claude-strict"):
        s = ailib.spec_for(name)
        assert s.model == ailib.CLAUDE_DEFAULT_MODEL == "claude-opus-5", name
        argv, _, honoured = SubprocessCli()._argv(s, Request(prompt="p"), "claude", __import__("pathlib").Path("."))
        assert "--model" in argv and argv[argv.index("--model") + 1] == "claude-opus-5", name
        assert "model" in honoured
    assert ailib.spec_for("claude", model="claude-sonnet-5").model == "claude-sonnet-5"
    assert ailib.spec_for("codex").model == ""                       # codex keeps the CLI's own default


def test_codex_is_exec_on_stdin_with_a_model_flag():
    s = ailib.spec_for("codex")
    assert s.transport == "cli" and s.command[:3] == ("codex", "exec", "--skip-git-repo-check")
    assert s.command[-1] == "-" and "{model}" in " ".join(s.command)
    assert s.on_prem is False and s.candidates                # the npm / WinGet shims


def test_lmstudio_is_the_openai_compat_transport_on_loopback_with_reasoning_off():
    s = ailib.spec_for("lmstudio")
    assert s.transport == "openai_compat" and s.endpoint == "http://127.0.0.1:1234/v1"
    assert "localhost" not in s.endpoint                      # IPv4 literal on purpose
    assert dict(s.extra)["reasoning_effort"] == "none"
    assert "Developer tab" in s.hint
    assert s.credential_env == ""
    assert "data_stays_on_prem" in build(s).capabilities


def test_openrouter_is_the_same_transport_over_the_wire_with_a_named_key(monkeypatch):
    s = ailib.spec_for("openrouter")
    assert s.transport == "openai_compat" and s.endpoint == "https://openrouter.ai/api/v1"
    assert s.credential_env == "OPENROUTER_API_KEY"
    assert "data_stays_on_prem" not in build(s).capabilities
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    ready = build(s).probe()
    assert ready.ok is False and "OPENROUTER_API_KEY" in ready.reason and "not set" in ready.reason


def test_ollama_and_openai_are_presets_too():
    assert ailib.spec_for("ollama").endpoint == "http://127.0.0.1:11434/v1"
    o = ailib.spec_for("openai")
    assert o.endpoint == "https://api.openai.com/v1" and o.credential_env == "OPENAI_API_KEY"


def test_the_cli_presets_carry_a_tools_grant_that_only_a_workdir_unlocks():
    """U3 of #64. claude and codex gain the flag their sandbox measurement
    proved (probe_claude_sandbox.py, probe_codex_sandbox.py, 2026-09-09):
    `--allowedTools Read,Grep,Edit,Write` writes only inside the cwd;
    `-s workspace-write` likewise. Without a workdir on the request the
    placeholder and its flag vanish, so pass 1's argv is unchanged; the
    servers have no grant at all."""
    from pathlib import Path
    from dazzle_claude_config._vendor.ailib.transports.cli import SubprocessCli
    from dazzle_claude_config._vendor.ailib.types import Request
    c = ailib.spec_for("claude")
    assert ("--allowedTools", "{tools}") in tuple(zip(c.command, c.command[1:]))
    assert c.tools == "Read,Grep,Edit,Write" and "tools" in build(c).capabilities
    x = ailib.spec_for("codex")
    assert x.command[:3] == ("codex", "exec", "--skip-git-repo-check")        # the pinned prefix stands
    assert ("-s", "{tools}") in tuple(zip(x.command, x.command[1:]))
    assert x.tools == "workspace-write" and "tools" in build(x).capabilities
    # the strict variants carry the SAME grant as their base preset (v0.6.3
    # sweep, survivor ailib-4: a narrower literal on one of them survived)
    assert ailib.spec_for("claude-strict").tools == c.tools == "Read,Grep,Edit,Write"
    assert ailib.spec_for("codex-strict").tools == x.tools == "workspace-write"
    assert ailib.spec_for("lmstudio").tools == "" and "tools" not in build(ailib.spec_for("lmstudio")).capabilities
    # pass 1's argv, byte for byte: no workdir, no grant on the command line
    argv, _, honoured = SubprocessCli()._argv(c, Request(prompt="p"), "claude", Path("."))
    assert argv == ["claude", "--output-format", "text", "--model", "claude-opus-5", "-p", "-"]
    assert "tools" not in honoured
    argv, _, _ = SubprocessCli()._argv(x, Request(prompt="p"), "codex", Path("."))
    assert argv == ["codex", "exec", "--skip-git-repo-check", "-"]
    # with a workdir the grant rides along
    argv, _, honoured = SubprocessCli()._argv(c, Request(prompt="p", workdir="C:/sandbox"), "claude", Path("."))
    assert argv[argv.index("--allowedTools") + 1] == "Read,Grep,Edit,Write" and "tools" in honoured


# -- overrides from the person's config ------------------------------------------

def test_config_overrides_endpoint_model_and_key_name():
    s = ailib.spec_for("lmstudio", endpoint="http://192.168.1.5:1234/v1", model="qwen", api_key_env="MY_KEY")
    assert s.endpoint == "http://192.168.1.5:1234/v1" and s.model == "qwen" and s.credential_env == "MY_KEY"
    assert dict(s.extra)["reasoning_effort"] == "none"        # the preset's extras survive
    c = ailib.spec_for("claude", model="opus-4")
    assert c.model == "opus-4"


def test_spec_for_maps_the_read_order(tmp_path):
    """K5 (2026-09-09). The library's order is fixed -- a named file, the
    environment, fallback files -- and ccs maps its own onto it: an explicit
    `ai_merge_api_key_file` is the named file (read first), the keys
    directory's `<preset>.env` is the one fallback (read after the
    environment), and a preset that names no credential variable gets no
    fallback at all, so no file is ever looked for on its behalf."""
    keys = tmp_path / "keys"
    s = ailib.spec_for("openrouter", api_key_file="/keys/mine.env", keys_dir=keys)
    assert s.credential_file == "/keys/mine.env"
    assert s.credential_fallbacks == (str(keys / "openrouter.env"),)
    assert s.credential_env == "OPENROUTER_API_KEY"                 # the line the file must carry
    assert ailib.spec_for("openrouter").credential_fallbacks == ()  # no keys dir given: none
    assert ailib.spec_for("openrouter").credential_file == ""
    assert ailib.spec_for("lmstudio", keys_dir=keys).credential_fallbacks == ()   # needs no key
    # an overridden variable name still earns the preset-named file, looked up by THAT name
    s2 = ailib.spec_for("lmstudio", api_key_env="MY_KEY", keys_dir=keys)
    assert s2.credential_env == "MY_KEY" and s2.credential_fallbacks == (str(keys / "lmstudio.env"),)
    assert ailib.keys_dir(tmp_path) == keys


def test_build_backend_carries_the_key_file_and_the_keys_dir(tmp_path):
    from dazzle_claude_config import aistep
    opts = aistep.AiOptions(rules_dir=tmp_path, prompts_dir=tmp_path, cache_dir=tmp_path,
                            backend="openrouter", api_key_file="/keys/mine.env",
                            keys_dir=tmp_path / "keys")
    spec = ailib.build_backend(opts).spec
    assert spec.credential_file == "/keys/mine.env"
    assert spec.credential_fallbacks == (str(tmp_path / "keys" / "openrouter.env"),)
    # the defaults stand for a constructor that never heard of them
    bare = aistep.AiOptions(rules_dir=tmp_path, prompts_dir=tmp_path, cache_dir=tmp_path, backend="openrouter")
    assert ailib.build_backend(bare).spec.credential_fallbacks == ()


def test_a_preset_is_never_mutated_by_an_override():
    before = ailib.spec_for("lmstudio")
    ailib.spec_for("lmstudio", model="x")
    assert ailib.spec_for("lmstudio") == before


def test_the_strict_variants_carry_an_answer_locator():
    """claude --output-format json --json-schema answers in an envelope whose
    key is structured_output (measured from the Claude Code source on
    2026-09-05); codex -o writes the last message to a file. Both are
    experiments for the witnessed runs, not the defaults."""
    cs = ailib.spec_for("claude-strict")
    assert cs.answer == "stdout-json:structured_output" and "{schema}" in " ".join(cs.command)
    xs = ailib.spec_for("codex-strict")
    assert xs.answer == "file:{output_file}" and "{schema_file}" in " ".join(xs.command)
    assert "schema" in build(cs).capabilities and "schema" in build(xs).capabilities
    assert "schema" not in build(ailib.spec_for("claude")).capabilities
