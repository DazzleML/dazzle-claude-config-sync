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
from ._vendor.ailib.backends import prompt_only as _prompt_only

_BACKENDS_PKG = __name__.rsplit(".", 1)[0] + "._vendor.ailib.backends"

# analyzer.py:32-36 spells the registry as ``wtf_windows.lib.ai.backends.*``.
# Rebinding the name is enough: ``get_backend`` reads the module global at
# call time, so the vendored file stays untouched.
_analyzer._BACKENDS = {
    "claude": _BACKENDS_PKG + ".claude",
    "codex": _BACKENDS_PKG + ".codex",
    "prompt-only": _BACKENDS_PKG + ".prompt_only",
}

PROMPT_ONLY = "prompt-only"


def backend_names() -> tuple[str, ...]:
    """The selectable backends, in registry order."""
    return tuple(_analyzer._BACKENDS)


def get_backend(name: str):
    """The backend module for `name`; ValueError names the known ones."""
    return _analyzer.get_backend(name)


def check_available(name: str) -> bool:
    """False for an unknown backend or one whose CLI is not installed."""
    return _analyzer.check_available(name)


def invoke(name: str, prompt: str, *, verbose: bool = False, timeout: int = 120,
           cwd: str | os.PathLike | None = None) -> tuple[bool, str]:
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
    before = os.getcwd()
    scratch: str | None = None
    try:
        if cwd is None:
            scratch = tempfile.mkdtemp(prefix="ccs-ai-")
            os.chdir(scratch)
        else:
            os.chdir(cwd)
        return backend.invoke(prompt, verbose=verbose, timeout=timeout)
    finally:
        os.chdir(before)
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
