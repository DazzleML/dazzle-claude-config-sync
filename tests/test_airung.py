"""U2 of the deep merge (#64): the rung classifier, `airung.py`.

Pure -- no manifest, no git, no model. It answers one question about a
candidate the deep step produced: how far from git's own changes did the
edits reach? The four rungs (the maintainer's ladder, 2026-09-06):

    1 hunk        inside a changed region of the payload file and its
                  surrounding code (the region under the same heading, or
                  the enclosing function or block)
    2 file        elsewhere in the payload file
    3 neighbours  another file the caller named a neighbour
    4 project     any other file

Written BEFORE the module (red by construction: ImportError until it
exists), so the audit at the pop has nothing to manufacture.
"""
from __future__ import annotations

import pytest

from bc_fixture import BASE, FIXED_BROKEN, FIXED_IN_A, MERGED_BROKEN


# -- the ladder's names ------------------------------------------------------------

def test_the_four_rungs_round_trip_between_token_and_number():
    from dazzle_claude_config import airung
    assert airung.RUNGS == ("hunk", "file", "neighbours", "project")
    for n, token in enumerate(airung.RUNGS, 1):
        assert airung.rung_of(token) == n and airung.token_of(n) == token
    with pytest.raises(ValueError):
        airung.rung_of("everything")
    with pytest.raises(ValueError):
        airung.token_of(5)


# -- the splitters -----------------------------------------------------------------

def _tiles(regions, text):
    """Every line belongs to exactly one region, in order."""
    n = len(text.splitlines())
    assert [r.start for r in regions] == [0] + [r.end for r in regions[:-1]]
    assert regions[-1].end == n


MD = """intro line one
intro line two

# Title

## Steps
1. run the report
2. read it

```
# not a heading: a comment inside a fence
```

### Detail
a nested section

## Notes
see the report
"""


def test_markdown_splits_from_each_heading_to_the_next_of_any_level():
    from dazzle_claude_config.airung import split_regions
    regions = split_regions(MD, "skills/think/SKILL.md")
    _tiles(regions, MD)
    assert [(r.kind, r.title) for r in regions] == [
        ("preamble", ""), ("heading", "Title"), ("heading", "Steps"),
        ("heading", "Detail"), ("heading", "Notes")]
    steps = regions[2]
    lines = MD.splitlines()
    assert lines[steps.start] == "## Steps"
    assert "# not a heading: a comment inside a fence" in lines[steps.start:steps.end]   # the fence held
    assert lines[regions[3].start] == "### Detail"          # a deeper heading still ends the section


def test_a_markdown_file_with_no_heading_is_one_preamble():
    from dazzle_claude_config.airung import split_regions
    text = "just prose\n\nmore prose\n"
    regions = split_regions(text, "notes.md")
    assert len(regions) == 1 and regions[0].kind == "preamble"
    _tiles(regions, text)


PY = """import os

CONST = 1


@decorator
def first(x):
    return x


class Thing:
    def method(self):
        # a comment inside the class
        return 1

    def other(self):
        return 2


def last():
    pass
"""


def test_python_splits_on_column_zero_defs_and_classes_with_decorators_attached():
    from dazzle_claude_config.airung import split_regions
    regions = split_regions(PY, "scripts/tool.py")
    _tiles(regions, PY)
    assert [(r.kind, r.title) for r in regions] == [
        ("toplevel", ""), ("def", "first"), ("class", "Thing"), ("def", "last")]
    lines = PY.splitlines()
    assert lines[regions[1].start] == "@decorator"           # the decorator belongs to first()
    thing = regions[2]
    assert "    def method(self):" in lines[thing.start:thing.end]   # methods stay inside the class
    assert "    def other(self):" in lines[thing.start:thing.end]


def test_powershell_and_shell_split_on_column_zero_functions():
    from dazzle_claude_config.airung import split_regions
    ps1 = "param($x)\n\nfunction One {\n    return 1\n}\n\nfunction Two {\n    if ($x) {\n        return 2\n    }\n}\n"
    regions = split_regions(ps1, "hooks/run.ps1")
    _tiles(regions, ps1)
    assert [(r.kind, r.title) for r in regions] == [("toplevel", ""), ("def", "One"), ("def", "Two")]
    sh = "set -e\n\none() {\n    echo 1\n}\n\nfunction two {\n    echo 2\n}\necho done\n"
    regions = split_regions(sh, "hooks/run.sh")
    _tiles(regions, sh)
    assert [(r.kind, r.title) for r in regions] == [
        ("toplevel", ""), ("def", "one"), ("def", "two"), ("toplevel", "")]


def test_anything_else_splits_on_blank_line_paragraphs():
    from dazzle_claude_config.airung import split_regions
    text = "one\nstill one\n\n\ntwo\n\nthree\n"
    regions = split_regions(text, "settings.json.tmpl")
    _tiles(regions, text)
    assert [r.kind for r in regions] == ["paragraph"] * 3
    assert [r.title for r in regions] == ["one", "two", "three"]


def test_an_empty_text_has_no_regions_and_every_splitter_agrees():
    from dazzle_claude_config.airung import split_regions
    for label in ("a.md", "a.py", "a.ps1", "a.sh", "a.txt"):
        assert split_regions("", label) == []


# -- the anchors -------------------------------------------------------------------

def test_anchors_are_the_spans_of_the_mechanical_result_that_differ_from_the_base():
    from dazzle_claude_config.airung import anchors
    base = "a\nb\nc\nd\ne\n"
    mech = "a\nB\nc\nd\nX\nY\ne\n"             # b -> B (a change); X, Y inserted before e
    assert anchors(base, mech) == [(1, 2), (4, 6)]
    deleted = "a\nc\nd\ne\n"                   # b deleted: an EMPTY span at the point of deletion
    assert anchors(base, deleted) == [(1, 1)]
    assert anchors(base, base) == []


def test_the_bc_fixture_anchors_are_c_and_b_never_a():
    from dazzle_claude_config.airung import anchors, split_regions
    spans = anchors(BASE, MERGED_BROKEN)
    regions = split_regions(MERGED_BROKEN, "merged.py")
    by_name = {r.title: r for r in regions}
    touched = {r.title for r in regions for a1, a2 in spans if a1 < r.end and a2 > r.start}
    assert touched == {"c", "b"}
    assert by_name["a"].start >= max(a2 for _, a2 in spans)


# -- the verdict -------------------------------------------------------------------

def _verdict(candidate, *, others=None, neighbours=frozenset(), label="merged.py"):
    from dazzle_claude_config.airung import needed_rung
    return needed_rung(label=label, base=BASE, mechanical=MERGED_BROKEN, candidate=candidate,
                       others=others or {}, neighbours=frozenset(neighbours))


def test_no_edits_is_rung_zero():
    v = _verdict(MERGED_BROKEN)
    assert v.needed == 0 and v.edits == ()


def test_the_hand_fix_inside_b_is_rung_1():
    """The b()/c() case: the fix lands in b(), a region git's own merge
    changed. That is the hunk rung -- the changed regions and their
    surrounding code."""
    v = _verdict(FIXED_BROKEN)
    assert v.needed == 1
    assert len(v.edits) == 1
    e = v.edits[0]
    assert e.path == "merged.py" and e.region == "b" and e.rung == 1
    assert e.removed == ("    return v * 2",) and e.added == ("    return (v[0] * 2, v[1] * 2)",)


def test_an_edit_to_a_which_neither_side_touched_is_rung_2():
    v = _verdict(FIXED_IN_A)
    assert v.needed == 2
    assert [(e.region, e.rung) for e in v.edits] == [("a", 2)]


def test_a_neighbouring_file_is_rung_3_and_a_far_file_is_rung_4():
    others = {"skills/helper.md": ("old\n", "new\n")}
    assert _verdict(MERGED_BROKEN, others=others, neighbours={"skills/helper.md"}).needed == 3
    assert _verdict(MERGED_BROKEN, others=others).needed == 4
    unchanged = {"skills/helper.md": ("same\n", "same\n")}
    assert _verdict(MERGED_BROKEN, others=unchanged).needed == 0      # a file read but not changed is no edit


def test_the_verdict_is_the_highest_rung_and_lists_every_edit():
    others = {"skills/helper.md": ("old\n", "new\n"), "README.md": (b"a\n", b"a\nb\n")}
    v = _verdict(FIXED_BROKEN, others=others, neighbours={"skills/helper.md"})
    assert v.needed == 4
    assert sorted((e.path, e.rung) for e in v.edits) == [
        ("README.md", 4), ("merged.py", 1), ("skills/helper.md", 3)]
    readme = next(e for e in v.edits if e.path == "README.md")
    assert readme.added == ("b",) and readme.removed == ()          # bytes accepted, diffed by line


MD_BASE = "# Doc\n\n## Steps\n1. run the report\n\n## Notes\nsee the report\n"
MD_MECH = "# Doc\n\n## Steps\n1. run the report\n\n## Notes\nsee the summary\n"   # theirs renamed it in Notes


def test_markdown_rung_1_is_the_section_under_the_same_heading():
    from dazzle_claude_config.airung import needed_rung
    in_notes = MD_MECH.replace("see the summary", "see the summary (was: the report)")
    v = needed_rung(label="skills/s.md", base=MD_BASE, mechanical=MD_MECH, candidate=in_notes,
                    others={}, neighbours=frozenset())
    assert v.needed == 1 and v.edits[0].region == "Notes"
    in_steps = MD_MECH.replace("1. run the report", "1. run the summary")
    v = needed_rung(label="skills/s.md", base=MD_BASE, mechanical=MD_MECH, candidate=in_steps,
                    others={}, neighbours=frozenset())
    assert v.needed == 2 and v.edits[0].region == "Steps"


def test_an_insertion_at_the_end_of_the_file_belongs_to_the_last_region():
    v = _verdict(MERGED_BROKEN + "\n\ndef d():\n    pass\n")
    assert v.needed == 2 and v.edits[0].region == "a"


# -- v0.6.2 mutation sweep (survivor kills) -----------------------------------------

def test_a_heading_indented_four_spaces_is_not_a_heading_M1():
    """v0.6.2 sweep, survivor M1: the ATX heading regex allows 0-3 leading
    spaces (CommonMark's own rule); four or more is an indented block, not
    a heading, and must not start a new region."""
    from dazzle_claude_config.airung import split_regions
    text = "# Title\nintro\n\n    # indented, not a heading\nmore\n"
    regions = split_regions(text, "notes.md")
    assert len(regions) == 1 and regions[0].kind == "heading" and regions[0].title == "Title"


def test_powershell_filter_blocks_are_recognised_like_function_blocks_M3():
    """v0.6.2 sweep, survivor M3: `filter` is a PowerShell block keyword
    alongside `function` and `workflow`; dropping it from the alternation
    silently stops splitting filter blocks out as their own region."""
    from dazzle_claude_config.airung import split_regions
    ps1 = "filter Squish {\n    $_ * 2\n}\n"
    regions = split_regions(ps1, "hooks/run.ps1")
    assert [(r.kind, r.title) for r in regions] == [("def", "Squish")]


def test_a_hyphenated_shell_function_name_after_the_function_keyword_M4():
    """v0.6.2 sweep, survivor M4: `_SH_FUNC`'s `function name` alternative
    allows hyphens in the name, matching the `name()` alternative; losing
    that on only one side is an inconsistent normalization loss."""
    from dazzle_claude_config.airung import split_regions
    sh = "function do-thing {\n    echo hi\n}\n"
    regions = split_regions(sh, "hooks/run.sh")
    assert [(r.kind, r.title) for r in regions] == [("def", "do-thing")]


def test_a_stacked_decorator_attaches_to_the_first_decorator_line_M7():
    """v0.6.2 sweep, survivor M7: `pending` must remember the FIRST
    decorator line of a def, not the last -- stacked decorators should
    all ride inside the same region, starting at the top decorator."""
    from dazzle_claude_config.airung import split_regions
    text = "@first\n@second\ndef thing():\n    return 1\n"
    regions = split_regions(text, "tool.py")
    assert [(r.kind, r.title) for r in regions] == [("def", "thing")]
    lines = text.splitlines()
    assert lines[regions[0].start] == "@first"


def test_a_closing_brace_with_a_trailing_comment_still_closes_the_block_M9():
    """v0.6.2 sweep, survivor M9: the close check tests that the column-0
    line OPENS with `}` (startswith), not that it ends with one -- a
    trailing comment after the brace must still close the block."""
    from dazzle_claude_config.airung import split_regions
    ps1 = "function One {\n    return 1\n} # end One\n\nfunction Two {\n    return 2\n}\n"
    regions = split_regions(ps1, "hooks/run.ps1")
    assert [(r.kind, r.title) for r in regions] == [("def", "One"), ("def", "Two")]


def test_an_anchor_exactly_at_a_regions_end_still_overlaps_that_region_M12():
    """v0.6.2 sweep, survivor M12: `_overlaps`' empty-span branch is
    inclusive on both ends (region.start <= a1 <= region.end) -- a
    deletion anchor sitting exactly at a paragraph's last line still
    marks that paragraph anchored."""
    from dazzle_claude_config.airung import needed_rung
    base = "one\n\nDELETED\ntwo\n"
    mechanical = "one\n\ntwo\n"
    candidate = "ONE\n\ntwo\n"
    v = needed_rung(label="notes.txt", base=base, mechanical=mechanical, candidate=candidate,
                    others={}, neighbours=frozenset())
    assert v.needed == 1
    assert v.edits[0].region == "one"


def test_an_edit_spanning_two_regions_needs_every_touched_region_anchored_M14():
    """v0.6.2 sweep, survivor M14: `anchored` requires EVERY touched
    region to hold an anchor (all()) -- one anchored region among several
    touched is not enough to earn rung 1."""
    from dazzle_claude_config.airung import needed_rung
    base = "AAA\nOLD\n\nBBB\nbbb2\n"
    mechanical = "AAA\naaa2\n\nBBB\nbbb2\n"
    candidate = "AAA\naaa2\nX\nY\nbbb2\n"
    v = needed_rung(label="notes.txt", base=base, mechanical=mechanical, candidate=candidate,
                    others={}, neighbours=frozenset())
    assert v.needed == 2
    assert v.edits[0].region == "AAA"


def test_an_insertion_at_a_regions_first_line_belongs_to_that_region_v066_M02():
    """v0.6.6 sweep (the deep golden set), survivor M02: `_touched` places
    an insertion whose point IS a region's first line in that region
    (`r.start <= i1`), not in the last region of the file. Here the model
    inserts a line right before the `# B` heading: B holds no anchor, so
    the edit is rung 2 under B -- not rung 1 under the anchored last
    section C, which is where the fall-through would put it."""
    from dazzle_claude_config.airung import needed_rung
    base = "# A\na\n\n# B\nb\n\n# C\nc\n"
    mechanical = "# A\na2\n\n# B\nb\n\n# C\nc2\n"                  # A and C are anchored; B is not
    candidate = "# A\na2\n\nNEW\n# B\nb\n\n# C\nc2\n"                # inserted at B's first line
    v = needed_rung(label="notes.md", base=base, mechanical=mechanical, candidate=candidate,
                    others={}, neighbours=frozenset())
    assert v.needed == 2
    assert [e.region for e in v.edits] == ["B"]
