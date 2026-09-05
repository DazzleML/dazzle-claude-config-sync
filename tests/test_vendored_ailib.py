"""a1 -- the vendored AI library and the facade that is ccs's only door to it.

The six files under ``dazzle_claude_config/_vendor/ailib/`` were copied from
wtf-windows' ``src/wtf_windows/lib/ai/`` on 2026-09-03, and are **customised
here since** -- our own instance of the vendor, the way a git subtree is, on
its way to becoming the shared library. So the guarantee is deliberately not
byte-identity with the origin (that lock was removed 2026-09-05; the policy
and the reasoning are at the top of ``_VENDORED.md``). Three invariants are
pinned here instead:

  purity  -- nothing under ``_vendor/`` knows ccs exists, so the tree stays
             liftable into the standalone library. This is the one that
             actually makes a copy adoptable, and it matters MORE now that
             the tree is expected to travel;
  honesty -- a copied file that differs from the fingerprint it arrived with
             must say so in _VENDORED.md's "Changes since the copy", and a
             file authored here must be named there too. A fork of record is
             useful exactly as long as its record is true;
  facade  -- every backend resolves to a module under ``_vendor``, and the
             facade's own additions behave.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import tempfile
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1] / "dazzle_claude_config"
VENDOR = PKG / "_vendor"
AILIB = VENDOR / "ailib"
RECORD = AILIB / "_VENDORED.md"

EXPECTED_FILES = {
    "__init__.py",
    "analyzer.py",
    "backends/__init__.py",
    "backends/claude.py",
    "backends/codex.py",
    "backends/prompt_only.py",
}

#: Authored HERE, inside the vendored tree: the shared library wants an
#: HTTP-server backend, and holding it outside would have meant ccs owning a
#: file every other consumer needs. It is bound by the purity rule exactly
#: like the copies -- no ccs import, no ccs token, stdlib only -- which is
#: what keeps it liftable. It has no origin fingerprint because it has no
#: origin; the changes list is the only thing that records it exists, which
#: is why a test below insists it is named there.
AUTHORED_FILES = {
    "backends/lmstudio.py",
}


def _vendored_py() -> list[Path]:
    return sorted(p for p in AILIB.rglob("*.py") if "__pycache__" not in p.parts)


def _norm_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# -- the tree ----------------------------------------------------------------

def test_vendor_tree_is_the_copies_plus_what_we_authored_for_upstream():
    assert (VENDOR / "__init__.py").is_file(), "_vendor must be a package"
    assert (AILIB / "__init__.py").is_file()
    names = {p.relative_to(AILIB).as_posix() for p in _vendored_py()}
    assert names == EXPECTED_FILES | AUTHORED_FILES, (
        "a file appeared under _vendor/ailib that the record does not classify -- "
        "add it to EXPECTED_FILES (copied from upstream, hashed) or to "
        "AUTHORED_FILES (written here for upstream, purity-checked only)")
    assert RECORD.is_file(), "_VENDORED.md must sit beside the copy"


# -- purity ------------------------------------------------------------------

_FORBIDDEN_TOKENS = ("dazzle_claude_config", "ccs_", "CCS_")
_REL_IMPORT = re.compile(r"^\s*from\s+(\.+)([\w.]*)\s+import\b")
_ABS_IMPORT = re.compile(r"^\s*(?:from|import)\s+dazzle_claude_config\b")


def test_purity_nothing_under_vendor_knows_ccs():
    """The copy must be liftable into the standalone library unchanged: no
    import of ccs, no relative import climbing out of ``_vendor/ailib``, and
    none of ccs's own tokens anywhere in the text."""
    bad: list[str] = []
    for p in _vendored_py():
        rel = p.relative_to(AILIB).as_posix()
        # The module's package, for resolving relative imports.
        pkg = "dazzle_claude_config._vendor.ailib"
        if p.parent != AILIB:
            pkg += "." + p.parent.relative_to(AILIB).as_posix().replace("/", ".")
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if _ABS_IMPORT.match(line):
                bad.append(f"{rel}:{n}: imports ccs: {line.strip()}")
            m = _REL_IMPORT.match(line)
            if m:
                target = importlib.util.resolve_name(m.group(1) + m.group(2), pkg)
                if not target.startswith("dazzle_claude_config._vendor.ailib"):
                    bad.append(f"{rel}:{n}: relative import leaves _vendor/ailib: {line.strip()}")
            for tok in _FORBIDDEN_TOKENS:
                if tok in line:
                    bad.append(f"{rel}:{n}: token {tok!r}: {line.strip()}")
    assert not bad, "\n".join(bad)


# -- honesty -----------------------------------------------------------------

def _recorded_hashes() -> dict[str, str]:
    """Rows of the origin-fingerprint table: | path | lines | sha256 |."""
    rows: dict[str, str] = {}
    for line in RECORD.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and re.fullmatch(r"[0-9a-f]{64}", cells[-1]):
            rows[cells[0].strip("`")] = cells[-1]
    return rows


def test_every_copied_file_has_the_fingerprint_it_arrived_with():
    """The table records what we RECEIVED, so an edited file can be told from
    an untouched one and the delta has something to be measured against. It
    is no longer a lock -- see the policy note at the top of _VENDORED.md."""
    recorded = _recorded_hashes()
    assert set(recorded) == EXPECTED_FILES, (
        f"_VENDORED.md must record an origin fingerprint for exactly the files "
        f"COPIED from upstream; got {sorted(recorded)}. A file authored here has no "
        f"origin to fingerprint and belongs in 'Changes since the copy'.")


def _changes_section() -> str:
    text = RECORD.read_text(encoding="utf-8")
    start = text.index("## Changes since the copy")
    end = text.index("\n## ", start + 1)
    return text[start:end]


def test_a_file_that_differs_from_its_origin_is_declared_in_the_changes_list():
    """The honesty rule that replaced byte-identity.

    Our copy is open to improvement -- that is the whole point of it -- so
    the guarantee is no longer that nothing changed, but that everything
    which changed is written down. A fork of record is useful exactly as
    long as its record is true, and the way a fork rots is that somebody
    edits a file, does not log it, and six months later nobody can say
    which lines are ours. This makes that mechanical rather than cultural.
    """
    recorded = _recorded_hashes()
    changes = _changes_section()
    undeclared = [rel for rel, sha in recorded.items()
                  if _norm_sha(AILIB / rel) != sha and rel not in changes]
    assert not undeclared, (
        f"these copied files differ from the fingerprint they arrived with and are "
        f"not named in _VENDORED.md's 'Changes since the copy': {undeclared}. Edit "
        f"them freely -- but say what you changed and why, or the record stops "
        f"being able to tell ours from theirs.")


def test_a_file_authored_here_is_declared_too():
    """The same rule from the other side: `lmstudio.py` has no origin
    fingerprint, so the only thing that records its existence is the
    changes list."""
    changes = _changes_section()
    for rel in AUTHORED_FILES:
        assert rel in changes, f"{rel} is authored here but not named in the changes list"


# -- the facade --------------------------------------------------------------

def test_facade_registry_resolves_into_vendor():
    from dazzle_claude_config import ailib
    names = ailib.backend_names()
    # lmstudio is in the registry like the rest: the tree it resolves into is
    # what the vendoring contract is about, not who typed the file.
    assert set(names) == {"claude", "codex", ailib.LMSTUDIO, ailib.PROMPT_ONLY}
    for name in names:
        mod = ailib.get_backend(name)
        assert mod.__name__.startswith("dazzle_claude_config._vendor.ailib.backends."), mod.__name__
        assert callable(mod.invoke) and callable(mod.is_available)
    assert ailib.check_available(ailib.PROMPT_ONLY) is True
    with pytest.raises(ValueError):
        ailib.get_backend("no-such-backend")


def test_prompt_only_writes_the_prompt_and_names_the_file(tmp_path):
    from dazzle_claude_config import ailib
    ailib.set_prompt_dir(tmp_path)
    ok, message = ailib.invoke(ailib.PROMPT_ONLY, "hello there")
    assert ok is False                       # the vendored contract: nothing was answered
    written = list(tmp_path.glob("prompt_*.md"))
    assert len(written) == 1
    assert written[0].read_text(encoding="utf-8") == "hello there"
    assert str(written[0]) in message


def test_parse_json_block_takes_the_last_fence():
    from dazzle_claude_config import ailib
    text = ("Thinking...\n```json\n{\"draft\": 1}\n```\nRevised:\n"
            "```json\n{\"hunks\": [{\"hunk\": 1, \"lines\": [\"O1\"]}]}\n```\nDone.")
    assert ailib.parse_json_block(text) == {"hunks": [{"hunk": 1, "lines": ["O1"]}]}


@pytest.mark.parametrize("text", ["no fences here", "```json\n{not json\n```", "", None])
def test_parse_json_block_returns_none_when_absent_or_invalid(text):
    from dazzle_claude_config import ailib
    assert ailib.parse_json_block(text) is None


def test_parse_json_block_reads_a_multi_line_body():
    """Mutation survivor N1 (v0.5.21 sweep): without DOTALL a body that spans
    lines -- the normal shape of a hunk answer -- never matched."""
    from dazzle_claude_config import ailib
    text = ("```json\n{\n  \"hunks\": [\n    {\"hunk\": 1, \"lines\": [\"O1\", \"T2\"]}\n  ]\n}\n```")
    assert ailib.parse_json_block(text) == {"hunks": [{"hunk": 1, "lines": ["O1", "T2"]}]}


def test_parse_json_block_ignores_fences_of_other_languages():
    """Mutation survivor N2: a loosened fence pattern parsed any fenced block.
    A ```python block that happens to hold a dict literal is not an answer."""
    from dazzle_claude_config import ailib
    assert ailib.parse_json_block("```python\n{\"hunks\": []}\n```") is None
    assert ailib.parse_json_block("```\n{\"hunks\": []}\n```") is None
    # ...and a json fence AFTER a python one is still found.
    text = "```python\n{\"draft\": 1}\n```\n```json\n{\"final\": 1}\n```"
    assert ailib.parse_json_block(text) == {"final": 1}


def test_invoke_removes_the_scratch_directory_afterwards(monkeypatch):
    """Mutation survivor N3: removing the scratch directory BEFORE changing
    back out of it fails silently on Windows (a process cannot delete its own
    working directory) and leaks one directory per call."""
    from dazzle_claude_config import ailib
    monkeypatch.setattr(ailib, "get_backend", lambda name: _FakeBackend)
    _FakeBackend.seen.clear()
    ailib.invoke("fake", "hi")
    assert not Path(_FakeBackend.seen["cwd"]).exists()


def test_cache_reexports_round_trip(tmp_path):
    """Mutation survivors N7/N8: the re-exported cache functions and the TTL
    constant must be the vendored ones, in the right roles."""
    from dazzle_claude_config import ailib
    key = ailib.cache_key({"base": "x"}, "claude", "ccs-merge")
    assert ailib.cache_read(key, "claude", tmp_path) is None
    ailib.cache_write(key, "claude", {"success": True, "raw_response": "r"}, tmp_path)
    got = ailib.cache_read(key, "claude", tmp_path)
    assert got is not None and got["raw_response"] == "r" and got["cached"] is True
    assert isinstance(ailib.CACHE_TTL_SECONDS, int) and ailib.CACHE_TTL_SECONDS == 24 * 60 * 60


class _FakeBackend:
    seen: dict = {}

    @staticmethod
    def is_available():
        return True

    @staticmethod
    def invoke(prompt, verbose=False, timeout=120):
        _FakeBackend.seen["cwd"] = os.getcwd()
        if prompt == "raise":
            raise RuntimeError("boom")
        return True, "ok"


def test_invoke_runs_the_backend_in_a_neutral_directory(monkeypatch):
    from dazzle_claude_config import ailib
    monkeypatch.setattr(ailib, "get_backend", lambda name: _FakeBackend)
    caller_cwd = os.getcwd()
    _FakeBackend.seen.clear()
    assert ailib.invoke("fake", "hi") == (True, "ok")
    ran_in = Path(_FakeBackend.seen["cwd"]).resolve()
    assert ran_in != Path(caller_cwd).resolve()
    assert str(ran_in).startswith(str(Path(tempfile.gettempdir()).resolve()))
    assert os.getcwd() == caller_cwd


def test_invoke_restores_cwd_even_when_the_backend_raises(monkeypatch):
    from dazzle_claude_config import ailib
    monkeypatch.setattr(ailib, "get_backend", lambda name: _FakeBackend)
    caller_cwd = os.getcwd()
    with pytest.raises(RuntimeError):
        ailib.invoke("fake", "raise")
    assert os.getcwd() == caller_cwd


class _KwargsBackend:
    seen: dict = {}

    @staticmethod
    def is_available():
        return True

    @staticmethod
    def invoke(prompt, verbose=False, timeout=120):
        _KwargsBackend.seen.update(prompt=prompt, verbose=verbose, timeout=timeout)
        return True, "ok"


def test_invoke_forwards_verbose_and_timeout_by_name(monkeypatch):
    """Mutation survivor M8 (v0.5.21 sweep): the two keyword arguments were
    swapped on the way to the backend and nothing noticed, because the fake
    backends above ignore them. A streaming flag handed to `timeout` and a
    timeout handed to `verbose` would fail on the real CLI backends only."""
    from dazzle_claude_config import ailib
    monkeypatch.setattr(ailib, "get_backend", lambda name: _KwargsBackend)
    _KwargsBackend.seen.clear()
    ailib.invoke("fake", "the prompt", verbose=True, timeout=7)
    assert _KwargsBackend.seen == {"prompt": "the prompt", "verbose": True, "timeout": 7}


def test_invoke_honours_an_explicit_cwd(monkeypatch, tmp_path):
    from dazzle_claude_config import ailib
    monkeypatch.setattr(ailib, "get_backend", lambda name: _FakeBackend)
    _FakeBackend.seen.clear()
    ailib.invoke("fake", "hi", cwd=tmp_path)
    assert Path(_FakeBackend.seen["cwd"]).resolve() == tmp_path.resolve()
