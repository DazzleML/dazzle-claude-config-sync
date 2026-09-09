"""The one door into the vendored AI library -- and the presets.

``_vendor/ailib/`` is the library: value types (a `Spec` you build a
backend from, a `Request` you ask it with, a `Response` that says what
happened), one transport per way of reaching a model (a subprocess CLI, an
OpenAI-compatible HTTP server, a prompt written to a file), a `Backend`
object with `probe()` and `invoke()`, a cache helper, and two generic
readers. It knows nothing of this tool -- a test proves no host token
appears anywhere under it -- so it can be lifted into the standalone
library unchanged.

What lives HERE, and only here, is what is genuinely this tool's:

  * the **presets** -- the named backends a person types after `--ai`, as
    DATA over the library's transports. The library knows `cli`, `openai_compat`
    and `prompt-file`; this file knows that `lmstudio` means the OpenAI
    transport at 127.0.0.1:1234 with reasoning turned off and a hint about
    the Developer tab, that `openrouter` is the same transport at
    openrouter.ai with a key named OPENROUTER_API_KEY, and that `claude` is
    the Claude Code CLI with two environment variables scrubbed. Local
    versus remote is an endpoint and a key, never code;
  * `names()`, the list `--ai`, `ai_merge_backend` and `ccs doctor` share;
  * `spec_for()` and `build_backend()`, which apply the person's overrides
    (`ai_merge_endpoint`, `ai_merge_model`, `ai_merge_api_key_env`,
    `ai_merge_api_key_file`) to a preset and build the object the caller
    talks to;
  * `keys_dir()`, where a hosted preset's key file lives by default
    (`~/claude/keys/<preset>.env`, user territory). The library's read order
    is fixed -- a file named on purpose, then the environment, then fallback
    files -- and `spec_for` maps this tool's order onto it: an explicit
    `ai_merge_api_key_file` becomes the named file, the keys directory the
    fallback, so the environment variable wins over the directory and the
    explicit file wins over both.

Everything the caller needs from the library is re-exported here so that
this stays the only module importing ``_vendor``: `build`, `run`,
`Request`, `parsers`.

The library returns strings and structures. It cannot write into a merge
workspace or a live tree: everything that installs or destroys stays in
``merge.py``, behind validation and ``--accept``.
"""
from __future__ import annotations

from pathlib import Path

from ._vendor.ailib import parsers                                  # noqa: F401
from ._vendor.ailib.backend import Backend as _Backend, build         # noqa: F401
from ._vendor.ailib.cache import run                                 # noqa: F401
from ._vendor.ailib.types import Request, Spec as _Spec              # noqa: F401

#: The mode that sends nothing: the prompt is written for a person to carry.
#: A mode of the caller, not a backend -- `spec_for` refuses it on purpose.
PROMPT_ONLY = "prompt-only"


# -- the presets ----------------------------------------------------------------
#
# The CLI presets carry the argv that live runs proved (claude: three merges
# on 2026-09-04/05; codex: its own --help, since its CLI is broken on this
# box). The `-strict` variants ask for the schema on the command line and say
# where the answer then comes out -- claude's `--output-format json` envelope
# keeps it under `structured_output` (read from the Claude Code source on
# 2026-09-05); codex's `-o FILE` writes the last message to a file. They are
# experiments for the witnessed runs, not the defaults, because the fenced
# JSON block the prompt asks for is what the live runs proved.

_CLAUDE_ENV_UNSET = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")     # the CLI refuses to nest
_CLAUDE_CANDIDATES = ("~/.local/bin/claude.exe", "~/.local/bin/claude")
_CODEX_CANDIDATES = ("%APPDATA%/npm/codex.cmd", "%LOCALAPPDATA%/Microsoft/WinGet/Links/codex.cmd")
#: The model the claude presets ask for when ai_merge_model is unset. The
#: maintainer's word (2026-09-05): merges through the Claude Code CLI use
#: Opus 5, not whatever the CLI's session happens to default to -- which is
#: a different model, and which a merge should not silently inherit.
CLAUDE_DEFAULT_MODEL = "claude-opus-5"

PRESETS: dict[str, _Spec] = {
    "claude": _Spec("cli", name="claude", model=CLAUDE_DEFAULT_MODEL,
                    command=("claude", "--output-format", "text", "--model", "{model}", "-p", "-"),
                    env_unset=_CLAUDE_ENV_UNSET, candidates=_CLAUDE_CANDIDATES, on_prem=False),
    "claude-strict": _Spec("cli", name="claude-strict", model=CLAUDE_DEFAULT_MODEL,
                           command=("claude", "--output-format", "json", "--model", "{model}",
                                    "--json-schema", "{schema}", "-p", "-"),
                           answer="stdout-json:structured_output",
                           env_unset=_CLAUDE_ENV_UNSET, candidates=_CLAUDE_CANDIDATES, on_prem=False),
    "codex": _Spec("cli", name="codex",
                   command=("codex", "exec", "--skip-git-repo-check", "-m", "{model}", "-"),
                   candidates=_CODEX_CANDIDATES, on_prem=False),
    "codex-strict": _Spec("cli", name="codex-strict",
                          command=("codex", "exec", "--skip-git-repo-check", "-m", "{model}",
                                   "--output-schema", "{schema_file}", "-o", "{output_file}", "-"),
                          answer="file:{output_file}", candidates=_CODEX_CANDIDATES, on_prem=False),
    "lmstudio": _Spec("openai_compat", name="lmstudio", endpoint="http://127.0.0.1:1234/v1",
                      extra=(("reasoning_effort", "none"),),
                      hint="in LM Studio: the Developer tab"),
    "ollama": _Spec("openai_compat", name="ollama", endpoint="http://127.0.0.1:11434/v1"),
    "openai": _Spec("openai_compat", name="openai", endpoint="https://api.openai.com/v1",
                    credential_env="OPENAI_API_KEY"),
    "openrouter": _Spec("openai_compat", name="openrouter", endpoint="https://openrouter.ai/api/v1",
                        credential_env="OPENROUTER_API_KEY"),
}


def names() -> tuple[str, ...]:
    """Everything `--ai` and `ai_merge_backend` accept: the mode that sends
    nothing, then the presets. `userconfig` duplicates this list ON PURPOSE
    (a config file must be checkable without importing the AI machinery);
    `ccs doctor` and a test compare the two."""
    return (PROMPT_ONLY, *PRESETS)


def keys_dir(user_claude: Path) -> Path:
    """`~/claude/keys` -- user territory, never the payload: one
    `<preset>.env` per provider, holding a `NAME=value` line. Read only when
    the environment variable has nothing; `ai_merge_api_key_file` names a
    file read before both."""
    return Path(user_claude) / "keys"


def spec_for(name: str, *, endpoint: str | None = None, model: str | None = None,
             api_key_env: str | None = None, api_key_file: str | None = None,
             keys_dir: Path | None = None) -> _Spec:
    """The preset `name` with the person's overrides applied. prompt-only is
    a mode of the caller, not a backend, and is refused here on purpose.

    The key's route, mapped onto the library's fixed order (named file,
    environment, fallbacks): `api_key_file` is the named file; when
    `keys_dir` is given and the spec names a credential variable at all,
    `<keys_dir>/<name>.env` is the one fallback. A preset that needs no key
    (the local servers) gets no fallback, so no file is ever looked for on
    its behalf. Computed HERE and not in `build_backend`, because doctor
    calls this directly and must report the same route a merge would take."""
    if name == PROMPT_ONLY:
        raise ValueError(f"{PROMPT_ONLY!r} is not a backend: it writes the prompt and stops")
    try:
        spec = PRESETS[name]
    except KeyError:
        raise ValueError(f"unknown AI backend {name!r} -- one of: {', '.join(names())}") from None
    changes = {}
    if endpoint:
        changes["endpoint"] = str(endpoint)
    if model:
        changes["model"] = str(model)
    if api_key_env:
        changes["credential_env"] = str(api_key_env)
    if api_key_file:
        changes["credential_file"] = str(api_key_file)
    spec = spec.with_(**changes) if changes else spec
    if keys_dir is not None and spec.credential_env:
        spec = spec.with_(credential_fallbacks=(str(Path(keys_dir) / f"{name}.env"),))
    return spec


def build_backend(opts) -> _Backend:
    """A backend for `opts` (an `aistep.AiOptions`, or anything with
    `backend`, `endpoint`, `model`, `api_key_env`, `api_key_file` and
    `keys_dir`). The single seam a test replaces to keep a real preset and a
    real cache while faking the transport."""
    return build(spec_for(opts.backend, endpoint=getattr(opts, "endpoint", None),
                          model=getattr(opts, "model", None),
                          api_key_env=getattr(opts, "api_key_env", None),
                          api_key_file=getattr(opts, "api_key_file", None),
                          keys_dir=getattr(opts, "keys_dir", None)))
