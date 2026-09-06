"""Shared AI analysis pipeline for wtf-windows diagnostic tools.

Orchestrates prompt building, backend invocation, and response parsing.
Each tool supplies its own domain-specific functions:

    from wtf_windows.lib.ai.analyzer import analyze

    result = analyze(
        results=investigation_data,
        fingerprint_fn=my_stable_fields,    # tool-specific cache fingerprint
        prompt_path=Path("prompts/diagnose.md"),
        cache_dir=Path.home() / ".wtf-locked" / "cache",
        tool_name="locked",
    )

The analyzer handles caching, backend dispatch, and response parsing.
Tools handle what makes their events semantically unique.
"""

import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .backend import build as _build
from .cache import run as _run
from .parsers import sections as _sections
from .types import Request as _Request, Spec as _Spec


# The three names the ORIGINAL front door knew, as specs over the object
# model. This is the shim's table, not a registry: a consumer that wants
# its own names keeps them on its own side and builds specs itself. The argv
# is what the original backends ran; the prompt-only directory is the
# original default.
#
# COMPAT(remove-after: wtf locked migrates to build/run)
_COMPAT_PRESETS = {
    "claude": _Spec("cli", name="claude",
                    command=("claude", "--output-format", "text", "-p", "-"),
                    env_unset=("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"),
                    candidates=("~/.local/bin/claude.exe", "~/.local/bin/claude"), on_prem=False),
    "codex": _Spec("cli", name="codex",
                   command=("codex", "exec", "--skip-git-repo-check", "-"),
                   candidates=("%APPDATA%/npm/codex.cmd",
                               "%LOCALAPPDATA%/Microsoft/WinGet/Links/codex.cmd"), on_prem=False),
    "prompt-only": _Spec("prompt-file", name="prompt-only",
                         endpoint=str(Path.home() / ".wtf-windows" / "ai")),
}

def check_available(backend_name="claude"):
    """Whether one of the original three backends is ready, by name.

    A thin wrapper: the answer is `build(spec).probe().ok` for the spec the
    name maps to. A consumer on the object model asks its backend directly.

    COMPAT(remove-after: wtf locked migrates to build/run)
    """
    spec = _COMPAT_PRESETS.get(backend_name)
    if spec is None:
        return False
    return _build(spec).probe().ok


def build_prompt(results, prompt_path, clean_fn=None):
    """Build the AI analysis prompt from investigation results.

    Args:
        results: dict from the tool's investigation
        prompt_path: Path to the tool's prompt template (.md file)
        clean_fn: Optional function to clean results before embedding in prompt
                  (e.g., removing large raw_output fields to save tokens)

    Returns:
        str: The complete prompt text
    """
    template = prompt_path.read_text(encoding="utf-8")

    evidence = clean_fn(results) if clean_fn else results
    evidence_json = json.dumps(evidence, indent=2, default=str)

    # Replace template placeholders
    prompt = template.replace("{evidence_json}", evidence_json)

    # Optional dump section (for tools that include crash dump analysis)
    dump_section = ""
    raw_output = (results.get("dump_analysis") or {}).get("raw_output")
    if raw_output:
        lines = raw_output.splitlines()
        if len(lines) > 200:
            raw_output = "\n".join(lines[-200:])
            raw_output = f"[...truncated to last 200 lines...]\n{raw_output}"
        dump_section = (
            "\n## Crash Dump Analysis (kd.exe !analyze -v output)\n\n"
            f"```\n{raw_output}\n```\n"
        )
    prompt = prompt.replace("{dump_section}", dump_section)

    return prompt


def analyze(
    results,
    fingerprint_fn,
    prompt_path,
    cache_dir,
    tool_name,
    backend_name="claude",
    clean_fn=None,
    response_sections=None,
    verbose=False,
    timeout=120,
    refresh=False,
):
    """Run AI analysis on investigation results.

    Args:
        results: dict from the tool's investigation
        fingerprint_fn: Callable[[dict], dict] -- extracts stable fields for
            cache key. Each tool defines what makes its events unique.
        prompt_path: Path to the tool's prompt template
        cache_dir: Path to the tool's cache directory
        tool_name: Tool identifier (included in cache key)
        backend_name: which AI backend to use (claude, codex, prompt-only)
        clean_fn: Optional callable to clean results before prompt building
        response_sections: Optional list of (key, regex_label) for parsing.
            Defaults to What Happened / Why / What To Do / Confidence.
        verbose: stream output in real-time
        timeout: seconds before timing out
        refresh: bypass cache (re-run analysis)

    Returns:
        dict with keys:
            success: bool
            raw_response: str
            sections: dict (parsed sections)
            error: str or None
            cached: bool (if from cache)
            cached_at: float (if from cache)

    This is the ORIGINAL front door, kept with its signature and its result
    shape for the one live caller that still uses it (wtf-windows'
    `wtf locked --ai`, tools/core/locked/locked.py). It is a thin wrapper:
    the prompt comes from `build_prompt`, the backend from the three-name
    table above, the answer from `cache.run` over `backend.build`, the
    sections from `parsers.sections`. No logic of its own. The migration is
    one call: `run(build(spec), Request(prompt), cache_dir=..., ...)`.

    COMPAT(remove-after: wtf locked migrates to build/run)
    """
    spec = _COMPAT_PRESETS.get(backend_name)
    if spec is None:
        return {"success": False, "raw_response": "", "sections": {},
                "error": f"Unknown AI backend: {backend_name!r}. Available: {', '.join(_COMPAT_PRESETS)}"}
    backend = _build(spec)
    ready = backend.probe()
    if not ready.ok:
        return {"success": False, "raw_response": "", "sections": {},
                "error": f"AI backend '{backend_name}' is not available ({ready.reason})"}
    prompt = build_prompt(results, prompt_path, clean_fn)
    req = _Request(prompt=prompt, timeout=timeout, stream_to=sys.stdout if verbose else None)
    resp = _run(backend, req, cache_dir=Path(cache_dir), fingerprint_extra=fingerprint_fn(results),
                refresh=refresh, tool=tool_name)
    if resp.status == "deferred":
        return {"success": False, "raw_response": "", "sections": {},
                "error": f"Prompt saved to: {resp.artifact}"}
    if not resp.ok:
        return {"success": False, "raw_response": resp.error, "sections": {}, "error": resp.error}
    result = {"success": True, "raw_response": resp.text,
              "sections": _sections(resp.text, response_sections), "error": None}
    if resp.cached:
        result["cached"] = True
        result["cached_at"] = resp.cached_at
    return result
