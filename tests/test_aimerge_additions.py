"""The `additions` hunk kind: both sides added lines where the base had
nothing, and added different things.

Found by the golden set's first live pass on Opus 5 (2026-09-05): the
interleaving fixture came back one side whole, and the rationale quoted the
paragraph report's own sentence -- "only one side can be taken whole" --
which is true of a rewrite and false of two additions. The default model
had ignored the hint; the stronger model obeyed it. So the classifier
learned the case, the report says the opposite for it, and the prompt
carries a rule for it.
"""
from __future__ import annotations

from pathlib import Path

from dazzle_claude_config import aimerge, aiprompt, airules

OURS, THEIRS = "Set the timeout to 30 seconds.", "Log every retry."


def _hunk(ours, base, theirs):
    return aimerge.Hunk(1, ours, base, theirs)


def _no_rules():
    return airules.load_rules("skills/s.md", Path("no-such-dir-anywhere"))


def test_two_different_additions_over_an_empty_base_are_additions():
    assert _hunk([OURS], [], [THEIRS]).kind == "additions"
    assert _hunk(["a", "b"], [], ["c"]).kind == "additions"


def test_similar_additions_are_still_a_side_pick():
    """Both wrote the same new thing differently: a paragraph (or a rewrite),
    not two additions to keep."""
    assert _hunk(["A added here"], [], ["B added here"]).kind == "paragraph"
    assert _hunk(["abcd", "wxyz"], [], ["abef", "wxuv"]).kind == "rewrite"


def test_a_non_empty_base_is_never_additions():
    assert _hunk([OURS], ["old"], [THEIRS]).kind == "paragraph"


def test_one_sided_or_blank_hunks_are_not_additions():
    assert _hunk(["x"], [], []).kind == "lines"
    assert _hunk([" "], [], ["y"]).kind == "lines"


def test_the_report_says_both_can_be_kept():
    lines = aimerge.sub_line_report(_hunk([OURS], [], [THEIRS]))
    assert len(lines) == 1
    assert "both sides added" in lines[0] and "keeping both" in lines[0] and "either order" in lines[0]


def test_the_prompt_renders_the_kind_the_report_and_the_rule():
    text = aiprompt.build_prompt("skills/s.md", [_hunk([OURS], [], [THEIRS])], _no_rules(), "")
    assert "(additions)" in text
    assert "keeping both" in text                       # the report line, in the prompt
    assert "A hunk marked **additions**" in text        # the template's rule


def test_selecting_both_passes_the_check_and_assembles_in_the_chosen_order():
    h = _hunk([OURS], [], [THEIRS])
    both = {1: aiprompt.Choice(hunk=1, lines=["O1", "T1"], rules=[], rationale="both")}
    assert aiprompt.check_proposal([h], both, _no_rules()) == []
    assert aiprompt.resolve([h], both)[1] == [OURS, THEIRS]
    reversed_ = {1: aiprompt.Choice(hunk=1, lines=["T1", "O1"], rules=[], rationale="both")}
    assert aiprompt.check_proposal([h], reversed_, _no_rules()) == []
    assert aiprompt.resolve([h], reversed_)[1] == [THEIRS, OURS]


def test_dropping_one_addition_without_a_rule_is_refused():
    h = _hunk([OURS], [], [THEIRS])
    one = {1: aiprompt.Choice(hunk=1, lines=["O1"], rules=[], rationale="ours only")}
    failures = aiprompt.check_proposal([h], one, _no_rules())
    assert failures and any("T1" in f for f in failures)
