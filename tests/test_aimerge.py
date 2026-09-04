"""a2 -- the hunk model behind `ccs merge --ai`.

`git merge-file --diff3` has already classified a merge: what it resolved
is clean text, and every conflict hunk is a region BOTH sides changed. The
AI step only ever addresses those hunks, by line id, so the parser here is
the boundary of what a model can touch. Pure functions over strings: no
git, no manifest, no ccs imports.
"""
from __future__ import annotations

import pytest

from dazzle_claude_config import aimerge

DIFF3 = (
    "# Title\n"
    "\n"
    "intro line one\n"
    "intro line two\n"
    "intro line three\n"
    "intro line four\n"
    "<<<<<<< ours\n"
    "ours A\n"
    "ours B\n"
    "||||||| base\n"
    "base A\n"
    "=======\n"
    "theirs A\n"
    "theirs B\n"
    "theirs C\n"
    ">>>>>>> theirs\n"
    "middle one\n"
    "middle two\n"
    "<<<<<<< ours\n"
    "second ours\n"
    "||||||| base\n"
    "=======\n"
    "second theirs\n"
    ">>>>>>> theirs\n"
    "tail\n"
)


def test_parse_finds_both_hunks_with_their_panes_and_capped_context():
    parsed = aimerge.parse_diff3(DIFF3)
    assert len(parsed.hunks) == 2
    h1, h2 = parsed.hunks
    assert (h1.n, h2.n) == (1, 2)
    assert h1.ours == ["ours A", "ours B"]
    assert h1.base == ["base A"]
    assert h1.theirs == ["theirs A", "theirs B", "theirs C"]
    # context: at most 3 clean lines each side, never the markers
    assert h1.before == ["intro line two", "intro line three", "intro line four"]
    assert h1.after == ["middle one", "middle two"]
    assert h2.before == ["middle one", "middle two"]
    assert h2.after == ["tail"]
    assert h2.base == []
    # the clean text is intact and in order
    kinds = [s.kind for s in parsed.segments]
    assert kinds == ["clean", "hunk", "clean", "hunk", "clean"]
    assert parsed.segments[0].lines[0] == "# Title"
    assert parsed.trailing_newline is True


def test_parse_accepts_a_hunk_without_a_base_marker():
    text = "a\n<<<<<<< ours\nX\n=======\nY\n>>>>>>> theirs\nb"
    parsed = aimerge.parse_diff3(text)
    assert len(parsed.hunks) == 1
    assert parsed.hunks[0].ours == ["X"] and parsed.hunks[0].base == [] and parsed.hunks[0].theirs == ["Y"]
    assert parsed.trailing_newline is False


def test_parse_with_no_hunks_is_one_clean_segment():
    parsed = aimerge.parse_diff3("just\ntext\n")
    assert parsed.hunks == []
    assert len(parsed.segments) == 1 and parsed.segments[0].kind == "clean"
    assert aimerge.assemble(parsed, {}) == "just\ntext\n"


def test_ids_name_every_pane_line_and_nothing_else():
    h = aimerge.parse_diff3(DIFF3).hunks[0]
    ids = h.ids()
    assert ids == {"O1": "ours A", "O2": "ours B", "B1": "base A",
                   "T1": "theirs A", "T2": "theirs B", "T3": "theirs C"}
    assert "O3" not in ids and "before" not in ids


def test_kind_is_paragraph_for_single_line_panes_and_lines_otherwise():
    h1, h2 = aimerge.parse_diff3(DIFF3).hunks
    assert h1.kind == "lines"
    assert h2.kind == "paragraph"      # one line against one line
    rewrite = "<<<<<<< o\nalpha beta gamma delta\nepsilon zeta eta\n||||||| b\n=======\nalpha beta gamma delta!\nepsilon zeta eta theta\n>>>>>>> t\n"
    assert aimerge.parse_diff3(rewrite).hunks[0].kind == "rewrite"


def test_kind_edge_cases_pinned_by_the_sweep():
    """Mutation survivors M1/M2 (v0.5.21 sweep): two empty panes are not a
    rewrite of anything, and a pair sitting exactly on SUPERSEDE_RATIO is a
    rewrite -- 'at or above', as validate() reads the same threshold."""
    assert aimerge.Hunk(1, [], [], []).kind == "lines"
    assert aimerge.Hunk(1, ["", " "], [], ["", ""]).kind == "lines"
    # "abcd" vs "abef": 2 matching of 8 characters -> ratio exactly 0.5
    import difflib
    assert difflib.SequenceMatcher(None, "abcd", "abef").ratio() == aimerge.SUPERSEDE_RATIO
    assert aimerge.Hunk(1, ["abcd", "wxyz"], [], ["abef", "wxuv"]).kind == "rewrite"


def test_parse_emits_no_empty_clean_segment_around_adjacent_or_leading_hunks():
    """Mutation survivor N1 (round 2): a hunk that starts the file, or two
    hunks back to back, must not produce an empty clean segment between."""
    text = ("<<<<<<< ours\nX\n=======\nY\n>>>>>>> theirs\n"
            "<<<<<<< ours\nP\n=======\nQ\n>>>>>>> theirs\nz\n")
    parsed = aimerge.parse_diff3(text)
    assert [s.kind for s in parsed.segments] == ["hunk", "hunk", "clean"]
    assert parsed.hunks[0].after == [] and parsed.hunks[1].after == ["z"]
    assert aimerge.assemble(parsed, {1: ["X"], 2: ["Q"]}) == "X\nQ\nz\n"


def test_kind_is_not_paragraph_for_one_line_against_many():
    """Mutation survivor N7 (round 2): one line on one side and several on
    the other is a `lines` hunk -- the sub-line report has no pair to diff."""
    assert aimerge.Hunk(1, ["one"], [], ["one", "two"]).kind == "lines"
    assert aimerge.Hunk(1, ["one", "two"], [], ["one"]).kind == "lines"


def test_word_diff_splits_on_any_whitespace():
    """Mutation survivor N10 (round 2): a tab or a run of spaces is not a
    word; tokens are non-space runs, so these two lines are identical."""
    d = aimerge.word_diff("a\tb  c", "a b c")
    assert d.differences == 0 and d.ratio == 1.0 and d.ours_only == [] and d.theirs_only == []


def test_parse_keeps_the_last_line_of_an_unterminated_hunk():
    """Mutation survivor M6: an off-by-one on the walk dropped the final line
    of a hunk that reaches the end of the text."""
    parsed = aimerge.parse_diff3("a\n<<<<<<< ours\nX\n=======\nY\nZ")
    assert parsed.hunks[0].theirs == ["Y", "Z"]


def test_after_context_is_the_first_lines_of_the_next_clean_run():
    """Mutation survivor M9: the context AFTER a hunk must be the lines
    adjacent to it, not the far end of the clean run that follows."""
    text = ("<<<<<<< ours\nX\n=======\nY\n>>>>>>> theirs\n"
            "near one\nnear two\nnear three\nfar four\nfar five\n")
    h = aimerge.parse_diff3(text).hunks[0]
    assert h.after == ["near one", "near two", "near three"]
    assert h.before == []


def test_assemble_replaces_each_hunk_with_its_choice_and_keeps_the_rest():
    parsed = aimerge.parse_diff3(DIFF3)
    out = aimerge.assemble(parsed, {1: ["ours A", "theirs C"], 2: ["second theirs"]})
    assert out == (
        "# Title\n\nintro line one\nintro line two\nintro line three\nintro line four\n"
        "ours A\ntheirs C\n"
        "middle one\nmiddle two\n"
        "second theirs\n"
        "tail\n")
    assert "<<<<<<<" not in out and "=======" not in out


def test_assemble_refuses_an_unresolved_hunk():
    parsed = aimerge.parse_diff3(DIFF3)
    with pytest.raises(KeyError) as e:
        aimerge.assemble(parsed, {1: ["ours A"]})
    assert "hunk 2" in str(e.value)


def test_select_maps_ids_to_lines_in_the_given_order():
    h = aimerge.parse_diff3(DIFF3).hunks[0]
    assert aimerge.select(h, ["T1", "O2", "B1"]) == ["theirs A", "ours B", "base A"]
    with pytest.raises(KeyError):
        aimerge.select(h, ["O9"])


OURS_PARA = ("The frame keeps its name, because that is the name every document "
             "here uses; it covers ranking and doing.")
THEIRS_PARA = ("The frame answers to both names -- one older documents use, and PVMU; "
               "it covers prioritization and ordering and measuring and doing.")


def test_word_diff_reports_what_each_side_alone_has():
    d = aimerge.word_diff(OURS_PARA, THEIRS_PARA)
    assert "keeps its name, because that is the name every document here uses;" in d.ours_only
    assert "prioritization and ordering and measuring" in d.theirs_only
    assert d.differences >= 2
    assert 0.0 < d.ratio < 1.0
    same = aimerge.word_diff("a b c", "a b c")
    assert same.ours_only == [] and same.theirs_only == [] and same.differences == 0 and same.ratio == 1.0


def test_word_diff_counts_a_pure_deletion_by_theirs():
    """Mutation survivor M12: a run of words theirs dropped, with nothing in
    their place, is one difference and belongs to ours alone."""
    d = aimerge.word_diff("a b c d", "a d")
    assert d.ours_only == ["b c"] and d.theirs_only == [] and d.differences == 1
    d2 = aimerge.word_diff("a d", "a b c d")
    assert d2.ours_only == [] and d2.theirs_only == ["b c"] and d2.differences == 1


def test_sub_line_report_says_selection_takes_one_side_whole_and_lists_the_words():
    text = f"<<<<<<< o\n{OURS_PARA}\n||||||| b\nThe frame keeps its name.\n=======\n{THEIRS_PARA}\n>>>>>>> t\n"
    h = aimerge.parse_diff3(text).hunks[0]
    lines = aimerge.sub_line_report(h)
    assert lines[0].startswith("hunk 1: both sides rewrote the same paragraph")
    assert "one side whole" in lines[1]
    # each side's words on ITS line (mutation survivor M13: the arguments to
    # word_diff were swapped and the two lines traded contents unnoticed)
    theirs_line = next(l for l in lines if l.lstrip().startswith("theirs adds:"))
    ours_line = next(l for l in lines if l.lstrip().startswith("ours keeps:"))
    assert "prioritization and ordering" in theirs_line and "keeps its name" not in theirs_line
    assert "keeps its name" in ours_line and "prioritization" not in ours_line
    # a plain multi-line hunk gets no paragraph report, and neither does a
    # rewrite hunk (mutation survivor M14: a narrowed guard let one through)
    assert aimerge.sub_line_report(aimerge.parse_diff3(DIFF3).hunks[0]) == []
    rewrite = "<<<<<<< o\nalpha beta gamma delta\nepsilon zeta eta\n||||||| b\n=======\nalpha beta gamma delta!\nepsilon zeta eta theta\n>>>>>>> t\n"
    assert aimerge.sub_line_report(aimerge.parse_diff3(rewrite).hunks[0]) == []
