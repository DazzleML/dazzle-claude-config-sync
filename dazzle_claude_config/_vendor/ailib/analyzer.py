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
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


# Cache TTL
_CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 hours

# Available backends (lazy-loaded)
_BACKENDS = {
    "claude": "wtf_windows.lib.ai.backends.claude",
    "codex": "wtf_windows.lib.ai.backends.codex",
    "prompt-only": "wtf_windows.lib.ai.backends.prompt_only",
}

# Default response section labels
DEFAULT_SECTIONS = [
    ("what_happened", r"What Happened:"),
    ("why", r"Why:"),
    ("what_to_do", r"What To Do:"),
    ("confidence", r"Confidence:"),
]


def get_backend(name="claude"):
    """Get a backend module by name."""
    if name not in _BACKENDS:
        raise ValueError(
            f"Unknown AI backend: {name!r}. "
            f"Available: {', '.join(_BACKENDS)}"
        )
    import importlib
    return importlib.import_module(_BACKENDS[name])


def check_available(backend_name="claude"):
    """Check if the specified backend is available."""
    try:
        backend = get_backend(backend_name)
        return backend.is_available()
    except (ValueError, ImportError):
        return False


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


def _cache_key(fingerprint, backend_name, tool_name):
    """Generate a cache key from fingerprint, backend, and tool name.

    Including tool_name prevents cross-tool cache collisions when
    different tools happen to produce similar fingerprints.
    """
    payload = json.dumps(fingerprint, sort_keys=True, default=str)
    payload += f"\n{backend_name}\n{tool_name}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _cache_read(cache_key, backend_name, cache_dir):
    """Try to read a cached AI response. Returns the result dict or None."""
    cache_file = cache_dir / f"ai_{backend_name}_{cache_key}.json"
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        cached_at = data.get("cached_at", 0)
        if time.time() - cached_at > _CACHE_TTL_SECONDS:
            cache_file.unlink(missing_ok=True)
            return None
        result = data.get("result")
        if result:
            result["cached"] = True
            result["cached_at"] = cached_at
        return result
    except (json.JSONDecodeError, KeyError, OSError):
        return None


def _cache_write(cache_key, backend_name, result, cache_dir):
    """Write an AI response to the cache."""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"ai_{backend_name}_{cache_key}.json"
        data = {
            "cached_at": time.time(),
            "backend": backend_name,
            "result": result,
        }
        cache_file.write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )
    except OSError:
        pass  # Cache write failure is non-fatal


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
    """
    skip_cache = backend_name == "prompt-only"

    # Check cache first
    if not refresh and not skip_cache:
        fingerprint = fingerprint_fn(results)
        key = _cache_key(fingerprint, backend_name, tool_name)
        cached = _cache_read(key, backend_name, cache_dir)
        if cached:
            return cached

    backend = get_backend(backend_name)

    if not backend.is_available():
        return {
            "success": False,
            "raw_response": "",
            "sections": {},
            "error": f"AI backend '{backend_name}' is not available",
        }

    prompt = build_prompt(results, prompt_path, clean_fn)
    success, output = backend.invoke(
        prompt, verbose=verbose, timeout=timeout
    )

    if not success:
        return {
            "success": False,
            "raw_response": output,
            "sections": {},
            "error": output,
        }

    sections = parse_response(output, response_sections)

    result = {
        "success": True,
        "raw_response": output,
        "sections": sections,
        "error": None,
    }

    # Cache successful results
    if not skip_cache:
        if not refresh:
            fingerprint = fingerprint_fn(results)
            key = _cache_key(fingerprint, backend_name, tool_name)
        _cache_write(key, backend_name, result, cache_dir)

    return result


def parse_response(text, sections=None):
    """Parse the AI response into structured sections.

    Args:
        text: Raw AI response text
        sections: List of (key, regex_label) tuples defining the sections.
            Defaults to: what_happened, why, what_to_do, confidence.

    Returns:
        dict with parsed section content
    """
    if sections is None:
        sections = DEFAULT_SECTIONS

    parsed = {}

    for i, (key, pattern) in enumerate(sections):
        if i < len(sections) - 1:
            next_patterns = [lbl for _, lbl in sections[i + 1:]]
            stop = "|".join(next_patterns)
            regex = rf"{pattern}\s*(.*?)(?=(?:{stop})|\Z)"
        else:
            regex = rf"{pattern}\s*(.*)"

        match = re.search(regex, text, re.DOTALL)
        if match:
            parsed[key] = match.group(1).strip()

    # If structured parsing failed, store the whole response
    if not parsed:
        parsed["raw"] = text.strip()

    return parsed
