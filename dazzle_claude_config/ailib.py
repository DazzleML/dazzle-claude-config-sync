"""The one door into the vendored AI library.

``_vendor/ailib/`` is wtf-windows' ``lib/ai`` copied byte-verbatim (see
``_vendor/ailib/_VENDORED.md``). Nothing in ccs imports it directly; this
module is the only path, so that the copy can be lifted out unchanged into
the standalone library when a second consumer adopts it, and so that the
things ccs needs on top of it live in exactly one place:

  * the backend registry -- ``analyzer.py`` names its backends by
    wtf-windows' module paths; that dict is REBOUND here to the copies under
    ``_vendor``, which keeps the file verbatim instead of editing three lines
    of it;
  * a neutral working directory for the CLI backends -- ``claude -p`` and
    ``codex`` inherit the caller's directory, and from a merge workspace or a
    project tree that would pull a project's own instruction files into a
    prompt about someone's configuration; every call runs from a throwaway
    directory (or an explicit one) and the caller's directory is restored
    even when the backend raises;
  * a JSON reader -- ccs's response format is one fenced JSON block, not the
    ``What Happened / Why`` sections the vendored parser knows.

The library returns strings and structures. It cannot write into a merge
workspace or a live tree: everything that installs or destroys stays in
``merge.py``, behind validation and ``--accept``.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from ._vendor.ailib import analyzer as _analyzer
from ._vendor.ailib.backends import lmstudio as _lmstudio
from ._vendor.ailib.backends import prompt_only as _prompt_only

_BACKENDS_PKG = __name__.rsplit(".", 1)[0] + "._vendor.ailib.backends"

# analyzer.py:32-36 spells the registry as ``wtf_windows.lib.ai.backends.*``.
# Rebinding the name is enough: ``get_backend`` reads the module global at
# call time, so the vendored file stays untouched.
_analyzer._BACKENDS = {
    "claude": _BACKENDS_PKG + ".claude",
    "codex": _BACKENDS_PKG + ".codex",
    # Authored here, in the vendored tree, and written to be contributed
    # upstream: an HTTP endpoint is a shape the shared library wants, not a
    # ccs peculiarity. `_VENDORED.md` records which files are upstream's and
    # which are ours; the purity test holds for both, which is what keeps
    # this one liftable.
    "lmstudio": _BACKENDS_PKG + ".lmstudio",
    "prompt-only": _BACKENDS_PKG + ".prompt_only",
}

PROMPT_ONLY = "prompt-only"
LMSTUDIO = "lmstudio"


def backend_names() -> tuple[str, ...]:
    """The selectable backends, in registry order."""
    return tuple(_analyzer._BACKENDS)


def get_backend(name: str):
    """The backend module for `name`; ValueError names the known ones."""
    return _analyzer.get_backend(name)


def check_available(name: str) -> bool:
    """False for an unknown backend or one whose CLI is not installed."""
    return _analyzer.check_available(name)


#: Which env var names the model, per backend. The vendored CLI backends
#: build their own argv and take no model parameter, so a model chosen out
#: here reaches them only through the environment. The Claude Code CLI reads
#: ANTHROPIC_MODEL (verified: an invalid value comes back as
#: `[claude-code:unrecognized_model]`), so claude is covered from here.
#: codex has `-m/--model` but no env equivalent we have verified, so it is
#: absent from this table ON PURPOSE and `model_is_honoured` says so -- a
#: setting that quietly does nothing is the defect this table exists to
#: stop, not one to spread. Giving codex its flag means passing
#: configuration INTO the call rather than around it, which is queued in
#: _vendor/ailib/_VENDORED.md.
_MODEL_ENV = {"claude": "ANTHROPIC_MODEL"}


def model_is_honoured(name: str) -> bool:
    """True when `name` can actually be told which model to use.

    `lmstudio` takes it directly; `claude` through the environment; `codex`
    not yet, because its model is an argv flag and the backend contract has
    nowhere to pass one; `prompt-only` has no model at all, which is not a
    gap in the same sense -- there is nothing there to honour.
    """
    return name == LMSTUDIO or name in _MODEL_ENV


def invoke(name: str, prompt: str, *, verbose: bool = False, timeout: int = 120,
           cwd: str | os.PathLike | None = None,
           model: str | None = None) -> tuple[bool, str]:
    """Run `prompt` through backend `name`; ``(success, text)`` as the
    vendored contract has it (``prompt-only`` answers ``(False, where it
    wrote the prompt)``).

    The vendored ``invoke`` takes no working directory and the CLI backends
    run in the inherited one. A single-threaded CLI can afford ``os.chdir``
    around the call: the caller's directory is restored in ``finally``, and
    the throwaway directory is removed afterwards. Pass `cwd` to run
    somewhere specific instead.
    """
    backend = get_backend(name)
    if model and name == LMSTUDIO:
        # A server-shaped backend takes its model as state, a CLI takes it
        # as environment; the caller says `model=` once and this decides how
        # it lands. Two callers each choosing a mechanism is how the model
        # came to be passed twice by two routes.
        _lmstudio.configure(model=model)
    before = os.getcwd()
    env_var = _MODEL_ENV.get(name) if model else None
    env_before = os.environ.get(env_var) if env_var else None
    scratch: str | None = None
    try:
        if env_var:
            os.environ[env_var] = model
        if cwd is None:
            scratch = tempfile.mkdtemp(prefix="ccs-ai-")
            os.chdir(scratch)
        else:
            os.chdir(cwd)
        return backend.invoke(prompt, verbose=verbose, timeout=timeout)
    finally:
        os.chdir(before)
        if env_var:                       # restore, even on a raise
            if env_before is None:
                os.environ.pop(env_var, None)
            else:
                os.environ[env_var] = env_before
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)


# The response cache, re-exported. Keyed on a fingerprint the CALLER builds
# (ccs: the hashes of base, ours, theirs, the rules file and the dossier), the
# backend, and a tool name so two tools' fingerprints cannot collide.
cache_key = _analyzer._cache_key
cache_read = _analyzer._cache_read
cache_write = _analyzer._cache_write
CACHE_TTL_SECONDS = _analyzer._CACHE_TTL_SECONDS


def set_prompt_dir(path: str | os.PathLike) -> None:
    """Where ``prompt-only`` writes its ``prompt_<timestamp>.md``."""
    _prompt_only.set_output_dir(Path(path))


def set_endpoint(url: str | None = None) -> None:
    """Where the local model server is, and the shape its answers must take.

    Named for what it sets, like `set_prompt_dir` beside it -- an earlier
    spelling (`set_local`) named the BACKEND instead, and took the model
    too, which left `aistep` handing the model to two different mechanisms
    and the reader working out which one applied. `invoke(model=...)` is now
    the only way to say which model, for every backend; this says only where
    the server is. The schema rides along because it is ccs's, not the
    library's: the backend enforces a shape it is given, never one it knows.
    """
    from .aiprompt import ANSWER_SCHEMA
    _lmstudio.configure(endpoint=url, schema=ANSWER_SCHEMA)


def local_describe(model: str | None = None) -> str:
    """`ccs doctor`'s line for the local endpoint: where, and what is loaded.

    Takes the model to CHECK and does not configure anything to answer --
    a health check that mutates the thing it reports on is one you cannot
    run twice and trust.
    """
    return _lmstudio.describe(model or None)


def local_context_is_roomy() -> bool:
    """True when the loaded model's context window is far larger than a merge
    needs -- reachable, but slow enough that a person will think it hung."""
    return _lmstudio.context_is_roomy()


_JSON_FENCE = re.compile(r"```json[ \t]*\r?\n(.*?)\r?\n[ \t]*```", re.DOTALL | re.IGNORECASE)


def parse_json_block(text: str | None):
    """The LAST fenced ```json block in `text`, parsed; None when there is
    none or it is not valid JSON.

    Last, not first: a model that thinks aloud may draft a block and then
    revise it, and the revision is the answer.
    """
    if not text:
        return None
    blocks = _JSON_FENCE.findall(text)
    if not blocks:
        return None
    try:
        return json.loads(blocks[-1])
    except ValueError:
        return None
