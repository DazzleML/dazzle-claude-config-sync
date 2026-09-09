"""The rung classifier: how far from git's own changes did an edit reach?

The deep merge (#64) lets a model read git's clean regions for meaning
and write text -- but only where the person's rung allows. The ladder,
in the maintainer's words (2026-09-06):

    1  hunk        the changed regions of the payload file and their
                   surrounding code -- the section under the same heading,
                   the enclosing function or block
    2  file        anywhere else in the payload file
    3  neighbours  another file the caller named a neighbour (the same
                   component's files, the files the payload's commit
                   touched with it, files that reference it by name)
    4  project     any other file under the checkout or the live component

This module is the pure half of that guarantee. It knows nothing of the
manifest, git, or a model: it is handed texts and a list of neighbour
paths, and it answers with the rung the candidate NEEDED and the edits
that decided it. Whether that rung is allowed, and what to do when it is
not, belongs to the caller (`aideep`).

Two ideas make "surrounding code" mechanical rather than a judgment:

* **Regions.** A file is split by its suffix into regions that tile it:
  Markdown from each ATX heading to the next heading of any level (the
  text before the first heading is one region); Python, PowerShell and
  shell into column-0 function and class blocks (decorators attached),
  with the top-level runs between them as regions of their own; anything
  else into blank-line paragraphs. A region is the unit "surrounding
  code" means.
* **Anchors.** Every span of git's mechanical result that differs from
  the base -- the conflict hunks the recipe resolved AND the one-sided
  changes git took on its own -- in one rule: `SequenceMatcher(base,
  mechanical)`'s non-equal opcodes. A region that contains an anchor is
  where the merge already changed things; an edit there is rung 1. An
  edit in a region with no anchor is rung 2: the file, but not the hunk.

An edit to another file is rung 3 when the caller listed that path among
the neighbours, else 4. The verdict is the highest rung of any edit; no
edits at all is 0.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

#: The ladder's tokens, in order; `--ai-scope` takes one of these.
RUNGS = ("hunk", "file", "neighbours", "project")


def rung_of(token: str) -> int:
    """The rung's number (1-4) for its token; ValueError otherwise."""
    try:
        return RUNGS.index(token) + 1
    except ValueError:
        raise ValueError(f"unknown scope {token!r} -- one of: {', '.join(RUNGS)}") from None


def token_of(n: int) -> str:
    """The token for a rung's number; ValueError outside 1-4."""
    if not 1 <= n <= len(RUNGS):
        raise ValueError(f"rung {n!r} is not one of 1..{len(RUNGS)}")
    return RUNGS[n - 1]


@dataclass(frozen=True)
class Region:
    """A run of lines [start, end) of one file, and what it is: `kind` is
    one of preamble, heading, def, class, toplevel, paragraph; `title` is
    the heading's text, the function's or class's name, a paragraph's
    first line -- "" for a preamble or a top-level run."""
    start: int
    end: int
    title: str
    kind: str


@dataclass(frozen=True)
class Edit:
    """One contiguous change the candidate made: where (the path and the
    region's name), how far it reached (the rung), and the lines removed
    and added, so a report can show it without a second diff."""
    path: str
    region: str
    rung: int
    removed: tuple[str, ...]
    added: tuple[str, ...]


@dataclass(frozen=True)
class Verdict:
    """`needed` is the highest rung of any edit -- 0 when the candidate is
    byte-for-byte the mechanical result and no other file changed."""
    needed: int
    edits: tuple[Edit, ...]


# -- the splitters -----------------------------------------------------------------

_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*#*[ \t]*$")
_PY_DEF = re.compile(r"^(?:async[ \t]+)?(def|class)[ \t]+([A-Za-z_]\w*)")
_PS1_FUNC = re.compile(r"^(?:function|filter|workflow)[ \t]+([\w.:-]+)", re.IGNORECASE)
_SH_FUNC = re.compile(r"^(?:function[ \t]+([\w.-]+)|([\w.-]+)[ \t]*\(\))")


def _suffix(label: str) -> str:
    name = label.replace("\\", "/").rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _md_starts(lines: list[str]) -> list[tuple[int, str, str]]:
    starts: list[tuple[int, str, str]] = [(0, "preamble", "")]
    in_fence = False
    for i, ln in enumerate(lines):
        s = ln.lstrip()
        if s.startswith("```") or s.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING.match(ln)
        if m:
            starts.append((i, "heading", (m.group(2) or "").strip()))
    if len(starts) > 1 and starts[1][0] == 0:
        starts.pop(0)                          # the file opens with a heading: no preamble
    return starts


def _py_starts(lines: list[str]) -> list[tuple[int, str, str]]:
    starts: list[tuple[int, str, str]] = []
    pending: int | None = None                 # the first decorator line of a def to come
    for i, ln in enumerate(lines):
        if not ln.strip() or ln[0] in " \t":
            continue                           # blank or indented: inside whatever is open
        if ln.startswith("#"):
            continue                           # a column-0 comment rides with its neighbour
        if ln.startswith("@"):
            if pending is None:
                pending = i
            continue
        m = _PY_DEF.match(ln)
        if m:
            starts.append((pending if pending is not None else i, m.group(1), m.group(2)))
            pending = None
            continue
        pending = None
        if not starts or starts[-1][1] != "toplevel":
            starts.append((i, "toplevel", ""))
    return starts


def _brace_starts(lines: list[str], func: re.Pattern) -> list[tuple[int, str, str]]:
    """PowerShell and shell: a column-0 function opens a block that a
    column-0 `}` closes; column-0 statements outside a block are
    top-level runs."""
    starts: list[tuple[int, str, str]] = []
    in_func = False
    for i, ln in enumerate(lines):
        if not ln.strip() or ln[0] in " \t":
            continue
        if in_func:
            if ln.startswith("}"):
                in_func = False
            continue
        m = func.match(ln)
        if m:
            name = next(g for g in m.groups() if g)
            starts.append((i, "def", name))
            in_func = True
            continue
        if ln.startswith("#"):
            continue
        if not starts or starts[-1][1] != "toplevel":
            starts.append((i, "toplevel", ""))
    return starts


def _paragraph_starts(lines: list[str]) -> list[tuple[int, str, str]]:
    starts: list[tuple[int, str, str]] = []
    previous_blank = True
    for i, ln in enumerate(lines):
        blank = not ln.strip()
        if not blank and previous_blank:
            starts.append((i, "paragraph", ln.strip()[:60]))
        previous_blank = blank
    return starts


def split_regions(text: str, label: str) -> list[Region]:
    """The regions of `text`, chosen by `label`'s suffix, tiling every
    line exactly once and in order. An empty text has none."""
    lines = text.splitlines()
    if not lines:
        return []
    suffix = _suffix(label)
    if suffix in ("md", "markdown"):
        starts = _md_starts(lines)
    elif suffix in ("py", "pyi"):
        starts = _py_starts(lines)
    elif suffix in ("ps1", "psm1"):
        starts = _brace_starts(lines, _PS1_FUNC)
    elif suffix in ("sh", "bash", "zsh"):
        starts = _brace_starts(lines, _SH_FUNC)
    else:
        starts = _paragraph_starts(lines)
    if not starts or starts[0][0] != 0:
        # whatever precedes the first recognised start (blank lines, a
        # comment block, an indented fragment) is a region of its own
        kind = "preamble" if suffix in ("md", "markdown") else \
            ("paragraph" if suffix not in ("py", "pyi", "ps1", "psm1", "sh", "bash", "zsh") else "toplevel")
        starts.insert(0, (0, kind, ""))
    regions = []
    for n, (start, kind, title) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        regions.append(Region(start, end, title, kind))
    return regions


# -- the anchors -------------------------------------------------------------------

def anchors(base: str, mechanical: str) -> list[tuple[int, int]]:
    """Every span [j1, j2) of `mechanical` that differs from `base` -- the
    hunks the recipe resolved and the one-sided changes git took, in one
    rule. A pure deletion is an empty span at the point of deletion."""
    sm = SequenceMatcher(None, base.splitlines(), mechanical.splitlines(), autojunk=False)
    return [(j1, j2) for tag, _i1, _i2, j1, j2 in sm.get_opcodes() if tag != "equal"]


def _overlaps(span: tuple[int, int], region: Region) -> bool:
    a1, a2 = span
    if a1 == a2:
        return region.start <= a1 <= region.end
    return a1 < region.end and a2 > region.start


def _touched(regions: list[Region], i1: int, i2: int) -> list[Region]:
    """The regions a span [i1, i2) of the mechanical text lies in; an
    empty span (an insertion) belongs to the region containing its
    point, or the last region when the point is the end of the file."""
    if not regions:
        return []
    if i1 == i2:
        for r in regions:
            if r.start <= i1 < r.end:
                return [r]
        return [regions[-1]]
    return [r for r in regions if r.start < i2 and r.end > i1] or [regions[-1]]


def _text(value) -> str:
    return value.decode("utf-8", "replace") if isinstance(value, (bytes, bytearray)) else str(value)


def needed_rung(*, label: str, base, mechanical, candidate, others: dict,
                neighbours: frozenset) -> Verdict:
    """The rung the candidate NEEDED, and the edits that decided it.

    `base`, `mechanical` and `candidate` are the payload file's three
    texts (str or bytes); `others` maps every other path the step could
    reach to its (before, after) bytes or text -- a path whose two are
    equal is not an edit; `neighbours` is the set of paths rung 3 covers.
    Edits inside the payload file are classified against the MECHANICAL
    text's regions and anchors: 1 when every region an edit touches
    holds an anchor, 2 otherwise."""
    base_t, mech_t, cand_t = _text(base), _text(mechanical), _text(candidate)
    regions = split_regions(mech_t, label)
    spans = anchors(base_t, mech_t)
    mech_lines, cand_lines = mech_t.splitlines(), cand_t.splitlines()
    edits: list[Edit] = []
    sm = SequenceMatcher(None, mech_lines, cand_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        touched = _touched(regions, i1, i2)
        anchored = bool(touched) and all(any(_overlaps(s, r) for s in spans) for r in touched)
        name = (touched[0].title or touched[0].kind) if touched else ""
        edits.append(Edit(path=label, region=name, rung=1 if anchored else 2,
                          removed=tuple(mech_lines[i1:i2]), added=tuple(cand_lines[j1:j2])))
    for path in sorted(others):
        before, after = others[path]
        b_t, a_t = _text(before), _text(after)
        if b_t == a_t:
            continue
        b_lines, a_lines = b_t.splitlines(), a_t.splitlines()
        removed: list[str] = []
        added: list[str] = []
        for tag, i1, i2, j1, j2 in SequenceMatcher(None, b_lines, a_lines, autojunk=False).get_opcodes():
            if tag != "equal":
                removed.extend(b_lines[i1:i2])
                added.extend(a_lines[j1:j2])
        edits.append(Edit(path=path, region="", rung=3 if path in neighbours else 4,
                          removed=tuple(removed), added=tuple(added)))
    return Verdict(needed=max((e.rung for e in edits), default=0), edits=tuple(edits))
