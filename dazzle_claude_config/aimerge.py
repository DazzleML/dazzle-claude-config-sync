"""The hunk model behind ``ccs merge --ai``: what a model may touch, by id.

``git merge-file --diff3`` has already classified a merge. Everything it
resolved is clean text -- one side changed it, or neither -- and every
conflict hunk is a region BOTH sides changed. The AI step addresses only
those hunks, and only by line id (``O1``, ``B2``, ``T3``: the ours, base and
theirs panes of one hunk), so this module is the boundary of what a model
can reach. It never sees the clean text except as a few marked context
lines, it cannot name a line that is not in a pane, and ccs reassembles the
file from its answer. That reassembly shape -- not the validator -- is what
makes "line selection only" hold (design of record: the 2026-09-03 final
assessment of the ``--ai`` consultation).

Pure functions over strings. No git, no manifest, no imports from the rest
of ccs, so the whole module is testable with a fixture string, and so it can
travel with the merge library when that leaves ccs.

The other thing here is the sub-line report. Measured on the maintainer's
real workspace on 2026-09-03: 31 merge inputs, one conflict hunk, and that
hunk was one 1431-character paragraph against one 1497-character paragraph
-- this house writes one line per paragraph, so the merge unit is a
paragraph and a line selector can only take one side whole. ``word_diff``
says which words each side alone has, so the person (and the prompt) get
what they would otherwise read out of two panes by eye.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

OURS_MARK = "<<<<<<<"
BASE_MARK = "|||||||"
SEP_MARK = "======="
THEIRS_MARK = ">>>>>>>"

#: Above this similarity a replaced line is a REWRITE of the same statement,
#: not a loss -- the same threshold ``merge.validate`` applies, so the two
#: gates tell one story about what a loss is.
SUPERSEDE_RATIO = 0.5

#: Clean lines shown around a hunk in the prompt, marked not selectable.
#: Capped so a generous window cannot smuggle the file back into the prompt.
CONTEXT_LINES = 3


@dataclass
class Hunk:
    """One conflict hunk: the three panes, in file order, with context."""
    n: int
    ours: list[str]
    base: list[str]
    theirs: list[str]
    before: list[str] = field(default_factory=list)   # clean context, not selectable
    after: list[str] = field(default_factory=list)

    def ids(self) -> dict[str, str]:
        """Every selectable line, by id. Context is deliberately absent."""
        out: dict[str, str] = {}
        for prefix, pane in (("O", self.ours), ("B", self.base), ("T", self.theirs)):
            for k, line in enumerate(pane, 1):
                out[f"{prefix}{k}"] = line
        return out

    @property
    def kind(self) -> str:
        """``paragraph``: one line against one line -- a side-pick for a line
        selector, and the case the sub-line report exists for. ``rewrite``:
        the same number of lines, each pair similar enough to be a rewrite of
        the same statement. ``lines``: anything else."""
        o = [l for l in self.ours if l.strip()]
        t = [l for l in self.theirs if l.strip()]
        b = [l for l in self.base if l.strip()]
        # Both sides ADDED, where the base had nothing, and added different
        # things: not a rewrite of any line, so "take one side whole" is the
        # wrong advice -- keeping both is a valid selection. Found by the
        # golden set on 2026-09-05: Opus 5 read the paragraph report's "only
        # one side" sentence on an interleaving and obeyed it. Similar added
        # lines stay a side-pick: both wrote the same new thing differently.
        if o and t and not b and not any(
                difflib.SequenceMatcher(None, a, c).ratio() >= SUPERSEDE_RATIO
                for a in o for c in t):
            return "additions"
        if len(o) == 1 and len(t) == 1:
            return "paragraph"
        if len(o) == len(t) and o and all(
                difflib.SequenceMatcher(None, a, b).ratio() >= SUPERSEDE_RATIO
                for a, b in zip(o, t)):
            return "rewrite"
        return "lines"


@dataclass
class Segment:
    """A run of clean lines, or a hunk, in file order."""
    kind: str                 # "clean" | "hunk"
    lines: list[str] = field(default_factory=list)
    hunk: Hunk | None = None


@dataclass
class Parsed:
    segments: list[Segment]
    hunks: list[Hunk]
    trailing_newline: bool


def parse_diff3(text: str, context: int = CONTEXT_LINES) -> Parsed:
    """Split ``git merge-file --diff3`` output into clean runs and hunks.

    The pane walk is ``basefind.restore_base_panes``' (copied, then adapted
    to keep positions and pane identity, which that function discards): a
    hunk runs from ``<<<<<<<`` to ``>>>>>>>``; ``|||||||`` starts the base
    pane and ``=======`` the theirs pane; a hunk without ``|||||||`` (plain
    merge style) has an empty base pane; an unterminated hunk ends at the
    end of the text.
    """
    lines = text.splitlines()
    segments: list[Segment] = []
    hunks: list[Hunk] = []
    clean: list[str] = []
    i = 0
    while i < len(lines):
        l = lines[i]
        if not l.startswith(OURS_MARK):
            clean.append(l)
            i += 1
            continue
        # collect one hunk
        j = i + 1
        ours_p: list[str] = []
        base_p: list[str] = []
        theirs_p: list[str] = []
        pane = ours_p
        bmark = smark = None
        while j < len(lines) and not lines[j].startswith(THEIRS_MARK):
            if lines[j].startswith(BASE_MARK):
                bmark = lines[j]; pane = base_p
            elif lines[j].startswith(SEP_MARK):
                smark = lines[j]; pane = theirs_p
            else:
                pane.append(lines[j])
            j += 1
        if clean:
            segments.append(Segment("clean", clean))
        hunk = Hunk(n=len(hunks) + 1, ours=ours_p, base=base_p, theirs=theirs_p,
                    before=clean[-context:] if context else [])
        hunks.append(hunk)
        segments.append(Segment("hunk", hunk=hunk))
        clean = []
        i = j + 1
    if clean:
        segments.append(Segment("clean", clean))
    for k, seg in enumerate(segments):
        if seg.kind == "hunk" and k + 1 < len(segments) and segments[k + 1].kind == "clean":
            seg.hunk.after = segments[k + 1].lines[:context] if context else []
    return Parsed(segments, hunks, trailing_newline=text.endswith("\n"))


def select(hunk: Hunk, ids: list[str]) -> list[str]:
    """The lines named by `ids`, in the given order. KeyError names an id
    that is not in this hunk's panes -- the formal check runs before this."""
    table = hunk.ids()
    out: list[str] = []
    for i in ids:
        if i not in table:
            raise KeyError(f"hunk {hunk.n}: no line {i!r} in its panes")
        out.append(table[i])
    return out


def assemble(parsed: Parsed, choices: dict[int, list[str]]) -> str:
    """The file with every hunk replaced by its chosen lines.

    `choices` maps a hunk number to the resolved lines. Every hunk must be
    resolved: a missing one is a KeyError, never a hunk left with markers in
    the output -- the validator would refuse that anyway, but a reassembly
    that silently emits markers is a false "done".
    """
    out: list[str] = []
    for seg in parsed.segments:
        if seg.kind == "clean":
            out.extend(seg.lines)
            continue
        h = seg.hunk
        if h.n not in choices:
            raise KeyError(f"hunk {h.n} has no resolution")
        out.extend(choices[h.n])
    text = "\n".join(out)
    if parsed.trailing_newline and out:
        text += "\n"
    return text


@dataclass
class WordDiff:
    """What each side alone has, as phrases, plus how alike the lines are."""
    ours_only: list[str]
    theirs_only: list[str]
    differences: int
    ratio: float


_TOKEN = re.compile(r"\S+")


def word_diff(ours_line: str, theirs_line: str) -> WordDiff:
    """A word-level comparison of two lines: contiguous runs of words that
    only one side has, in file order. Punctuation stays attached to its word,
    so a phrase reads as it appears."""
    o = _TOKEN.findall(ours_line)
    t = _TOKEN.findall(theirs_line)
    sm = difflib.SequenceMatcher(None, o, t, autojunk=False)
    ours_only: list[str] = []
    theirs_only: list[str] = []
    differences = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        differences += 1
        if i2 > i1:
            ours_only.append(" ".join(o[i1:i2]))
        if j2 > j1:
            theirs_only.append(" ".join(t[j1:j2]))
    return WordDiff(ours_only, theirs_only, differences, sm.ratio())


def _quoted(phrases: list[str]) -> str:
    return ", ".join(f'"{p}"' for p in phrases) if phrases else "(nothing)"


def sub_line_report(hunk: Hunk) -> list[str]:
    """For a paragraph hunk: the lines that say what line selection cannot
    do here and what each side alone has. For an additions hunk: the one
    line that says both CAN be kept. Empty for any other hunk."""
    if hunk.kind == "additions":
        o = [l for l in hunk.ours if l.strip()]
        t = [l for l in hunk.theirs if l.strip()]
        return [f"hunk {hunk.n}: both sides added here, where the base had nothing "
                f"({len(o)} vs {len(t)} line{'s' if len(o) + len(t) != 2 else ''}); "
                f"keeping both, in either order, is a valid selection."]
    if hunk.kind != "paragraph":
        return []
    o = next(l for l in hunk.ours if l.strip())
    t = next(l for l in hunk.theirs if l.strip())
    d = word_diff(o, t)
    n = d.differences
    return [
        f"hunk {hunk.n}: both sides rewrote the same paragraph "
        f"({len(o)} vs {len(t)} chars; {n} word-level difference{'s' if n != 1 else ''}).",
        "        Line selection can only take one side whole.",
        f"        theirs adds:  {_quoted(d.theirs_only)}",
        f"        ours keeps:   {_quoted(d.ours_only)}",
    ]
