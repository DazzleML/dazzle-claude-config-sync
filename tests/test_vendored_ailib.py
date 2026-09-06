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
The facade's own behaviour (presets, the object model, the transports) is
tested in tests/test_ailib_presets.py, test_ailib_types.py,
test_transport_*.py, test_ailib_cache.py and test_ailib_parsers.py; the
compatibility wrapper for the origin's caller in test_analyze_shim.py.
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

#: The copied files that remain. The four copied backends (claude, codex,
#: prompt_only and their __init__) were deleted on 2026-09-05 (U3 of the seam
#: rebuild) once every measured fact they carried had a home in the
#: transports; their origin fingerprints stay in _VENDORED.md's "Removed"
#: table, dated, so the record keeps what was received.
EXPECTED_FILES = {
    "__init__.py",
    "analyzer.py",
}

#: Authored HERE, inside the vendored tree, and bound by the purity rule
#: exactly like the copies -- no ccs import, no ccs token, stdlib only --
#: which is what keeps them liftable. They have no origin fingerprint because
#: they have no origin; the changes list is the only thing that records they
#: exist, which is why a test below insists each is named there.
AUTHORED_FILES = {
    # the object model of 2026-09-05 (U1 of the seam rebuild): a backend is a
    # frozen Spec built into an object with probe()/invoke(Request); one
    # transport per way of reaching a model; a cache helper; generic parsers
    "types.py",
    "backend.py",
    "cache.py",
    "parsers.py",
    "transports/__init__.py",
    "transports/cli.py",
    "transports/openai.py",
    "transports/prompt_file.py",
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
#
# The facade block that stood here (the registry rebinding, prompt-only via
# invoke, parse_json_block, the os.chdir scratch-directory tests, the cache
# re-exports, the kwargs forwarding) was retired on 2026-09-05 (U3 of the
# seam rebuild). Every property moved rather than vanished: the registry to
# tests/test_ailib_presets.py, prompt-only to test_transport_prompt_file.py,
# the JSON reader to test_ailib_parsers.py, the cache round trip to
# test_ailib_cache.py, the kwargs to Request, and the scratch-directory
# tests to test_transport_cli.py -- where the property is the OPPOSITE of
# the old one: cwd and environment are handed to the child and this process
# is never touched, checked at the moment subprocess.run is called.

def test_the_facade_is_the_only_module_that_imports_the_vendored_tree():
    """The purity test says nothing under _vendor/ knows ccs; this is the
    other direction: nothing in ccs reaches into _vendor/ except ailib.py,
    so lifting the tree out later touches exactly one import site."""
    offenders = []
    for p in PKG.rglob("*.py"):
        if "_vendor" in p.parts or p.name == "ailib.py":
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if "_vendor" in line and ("import" in line):
                offenders.append(f"{p.relative_to(PKG)}:{n}: {line.strip()}")
    assert not offenders, "\n".join(offenders)
