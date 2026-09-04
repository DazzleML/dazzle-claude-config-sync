"""a4 -- the prompt ccs builds for `--ai`, and the check every answer must pass.

The prompt carries the rules with their ids, the ancestry evidence in plain
words, and each conflict hunk with its lines named `O1..`, `B1..`, `T1..`
and its context marked not selectable. The answer names lines; ccs checks
it before a byte is assembled: every id exists, no text twice, each pane's
order kept, every unselected line either superseded by a selected rewrite
or licensed by a cited rule that exists, and base-only text brought back
only under a rule. Failures use their own `proposal:` family -- never the
validator's loss prefix, which a person may accept by hand.
"""
from __future__ import annotations

import pytest

from dazzle_claude_config import aimerge, aiprompt, airules

DIFF3 = (
    "# Title\n"
    "shared intro\n"
    "<<<<<<< ours\n"
    "keep the services section verbatim\n"
    "both sides have this line\n"
    "||||||| base\n"
    "an old base-only sentence\n"
    "=======\n"
    "both sides have this line\n"
    "install nginx and certbot before enabling the site\n"
    ">>>>>>> theirs\n"
    "tail\n"
)

OURS_PARA = "The frame keeps its name, because that is the name every document here uses; it covers ranking and doing."
THEIRS_PARA = "The frame keeps its name, the one every document here uses; it covers prioritization and ordering, measuring and doing."
PARA = f"a\n<<<<<<< o\n{OURS_PARA}\n||||||| b\nThe frame keeps its name.\n=======\n{THEIRS_PARA}\n>>>>>>> t\nz\n"

RULES_TEXT = ("# rules\n\nKEEP the services section verbatim.\n\n"
              "TAKE upstream's wording everywhere else.\n")


def _rules(tmp_path, text=RULES_TEXT):
    (tmp_path / "_default.md").write_text(text, encoding="utf-8")
    return airules.load_rules("x", tmp_path)


def _none_rules(tmp_path):
    return airules.load_rules("x", tmp_path / "empty")


# -- the prompt ----------------------------------------------------------------

def test_build_prompt_fills_every_slot_and_leaves_no_placeholder(tmp_path):
    parsed = aimerge.parse_diff3(DIFF3)
    text = aiprompt.build_prompt("dotclaude/CLAUDE.md", parsed.hunks, _rules(tmp_path),
                                 "the base is HEAD~2 (inferred); your live edit is uncommitted")
    assert "`dotclaude/CLAUDE.md`" in text
    assert "R1: KEEP the services section verbatim." in text
    assert "R2: TAKE upstream's wording everywhere else." in text
    assert "your live edit is uncommitted" in text
    assert "### Hunk 1" in text
    assert "O1: keep the services section verbatim" in text
    assert "B1: an old base-only sentence" in text
    assert "T2: install nginx and certbot before enabling the site" in text
    assert "context (not selectable)" in text and "shared intro" in text
    assert '{"hunks": [{"hunk": 1, "lines": ["O1", "O2", "T3"]' in text   # the example, braces intact
    for slot in ("{label}", "{rules}", "{dossier}", "{hunks}"):
        assert slot not in text


def test_prompt_says_when_there_are_no_rules_and_no_evidence(tmp_path):
    parsed = aimerge.parse_diff3(DIFF3)
    text = aiprompt.build_prompt("x", parsed.hunks, _none_rules(tmp_path), "")
    assert "rules: none" in text
    assert "nothing licenses a drop" in text
    assert "no ancestry evidence" in text


def test_render_hunks_marks_a_paragraph_hunk_and_an_empty_base():
    para = aimerge.parse_diff3(PARA).hunks[0]
    out = aiprompt.render_hunks([para])
    assert "### Hunk 1 (paragraph" in out
    assert "both sides rewrote the same paragraph" in out
    assert "theirs adds:" in out and "prioritization and ordering" in out
    no_base = aimerge.parse_diff3("<<<<<<< o\nX\n=======\nY\n>>>>>>> t\n").hunks[0]
    assert "nothing here in the common ancestor" in aiprompt.render_hunks([no_base])


# -- the answer ----------------------------------------------------------------

def test_parse_response_accepts_the_documented_shape():
    choices, failures = aiprompt.parse_response(
        {"hunks": [{"hunk": 1, "lines": ["O1", "T2"], "rules": ["R1"], "rationale": "why"}]})
    assert failures == []
    assert choices[1].lines == ["O1", "T2"] and choices[1].rules == ["R1"] and choices[1].rationale == "why"


@pytest.mark.parametrize("data", [
    None, [], {"answer": 1}, {"hunks": "no"}, {"hunks": [1]},
    {"hunks": [{"lines": ["O1"]}]},                       # no hunk number
    {"hunks": [{"hunk": "one", "lines": ["O1"]}]},
    {"hunks": [{"hunk": 1, "lines": "O1"}]},              # lines not a list
    {"hunks": [{"hunk": 1, "lines": [1]}]},
    {"hunks": [{"hunk": 1, "lines": ["O1"], "rules": "R1"}]},
])
def test_parse_response_rejects_malformed_answers(data):
    choices, failures = aiprompt.parse_response(data)
    assert failures and all(f.startswith("proposal:") for f in failures)


def test_parse_response_rejects_a_hunk_answered_twice():
    _, failures = aiprompt.parse_response(
        {"hunks": [{"hunk": 1, "lines": ["O1"]}, {"hunk": 1, "lines": ["T1"]}]})
    assert any("twice" in f for f in failures)


# -- the check -----------------------------------------------------------------

def _choice(n, lines, rules=(), rationale=""):
    return {n: aiprompt.Choice(n, list(lines), list(rules), rationale)}


def test_a_clean_interleaving_passes(tmp_path):
    h = aimerge.parse_diff3(DIFF3).hunks[0]
    # keep ours' first line (rule R1), the shared line once, and upstream's new line
    failures = aiprompt.check_proposal([h], _choice(1, ["O1", "O2", "T2"]), _rules(tmp_path))
    assert failures == []


def test_take_theirs_on_a_paragraph_needs_no_rule_because_it_is_a_rewrite(tmp_path):
    h = aimerge.parse_diff3(PARA).hunks[0]
    assert aiprompt.check_proposal([h], _choice(1, ["T1"]), _none_rules(tmp_path)) == []
    assert aiprompt.check_proposal([h], _choice(1, ["O1"]), _none_rules(tmp_path)) == []


def test_an_unknown_id_fails_and_names_it(tmp_path):
    h = aimerge.parse_diff3(DIFF3).hunks[0]
    failures = aiprompt.check_proposal([h], _choice(1, ["O1", "O9", "T2"]), _rules(tmp_path))
    assert any("O9" in f and f.startswith("proposal: hunk 1") for f in failures)


def test_the_same_text_twice_fails_even_from_two_panes(tmp_path):
    h = aimerge.parse_diff3(DIFF3).hunks[0]
    # O2 and T1 are the same text
    failures = aiprompt.check_proposal([h], _choice(1, ["O1", "O2", "T1", "T2"]), _rules(tmp_path))
    assert any("twice" in f for f in failures)


def test_a_pane_reordered_fails(tmp_path):
    h = aimerge.parse_diff3(DIFF3).hunks[0]
    failures = aiprompt.check_proposal([h], _choice(1, ["O2", "O1", "T2"]), _rules(tmp_path))
    assert any("order" in f and "O" in f for f in failures)


def test_a_dropped_line_needs_a_rule_that_exists(tmp_path):
    h = aimerge.parse_diff3(DIFF3).hunks[0]
    rules = _rules(tmp_path)
    # drop O1 ("keep the services section verbatim") with nothing cited
    failures = aiprompt.check_proposal([h], _choice(1, ["T1", "T2"]), rules)
    assert any("O1" in f and "no rule" in f for f in failures)
    # cite a rule that exists: licensed
    assert aiprompt.check_proposal([h], _choice(1, ["T1", "T2"], rules=["R2"]), rules) == []
    # cite one that does not exist: both the citation and the drop fail
    failures = aiprompt.check_proposal([h], _choice(1, ["T1", "T2"], rules=["R7"]), rules)
    assert any("R7" in f for f in failures) and any("O1" in f for f in failures)
    # with no rules file at all nothing can license it
    failures = aiprompt.check_proposal([h], _choice(1, ["T1", "T2"], rules=["R1"]), _none_rules(tmp_path))
    assert any("R1" in f for f in failures)


def test_a_shared_line_selected_once_is_not_a_drop_of_the_other_copy(tmp_path):
    h = aimerge.parse_diff3(DIFF3).hunks[0]
    # O2 == T1; selecting only T1 must not count O2 as dropped
    failures = aiprompt.check_proposal([h], _choice(1, ["O1", "T1", "T2"]), _rules(tmp_path))
    assert failures == []


def test_base_only_text_needs_a_rule(tmp_path):
    h = aimerge.parse_diff3(DIFF3).hunks[0]
    rules = _rules(tmp_path)
    failures = aiprompt.check_proposal([h], _choice(1, ["O1", "O2", "B1", "T2"]), rules)
    assert any("B1" in f and "base-only" in f for f in failures)
    assert aiprompt.check_proposal([h], _choice(1, ["O1", "O2", "B1", "T2"], rules=["R1"]), rules) == []


def test_every_hunk_needs_an_answer_and_only_real_hunks_may_be_answered(tmp_path):
    hunks = aimerge.parse_diff3(DIFF3 + "<<<<<<< o\nP\n=======\nQ\n>>>>>>> t\n").hunks
    assert len(hunks) == 2
    failures = aiprompt.check_proposal(hunks, {**_choice(1, ["O1", "O2", "T2"]), **_choice(3, ["O1"])},
                                       _rules(tmp_path))
    assert any("hunk 2" in f and "no resolution" in f for f in failures)
    assert any("hunk 3" in f and "no such hunk" in f for f in failures)


def test_a_dropped_payload_line_fails_like_a_dropped_live_one(tmp_path):
    """Mutation survivor M8 (v0.5.21 sweep): both panes are checked for
    drops, not only ours."""
    h = aimerge.parse_diff3(DIFF3).hunks[0]
    failures = aiprompt.check_proposal([h], _choice(1, ["O1", "O2"]), _none_rules(tmp_path))
    assert any("T2" in f and "no rule" in f for f in failures)


def test_the_base_pane_keeps_its_order_too(tmp_path):
    """Mutation survivor M6: B lines are order-checked like O and T."""
    text = "<<<<<<< o\nX\n||||||| b\nbase one\nbase two\n=======\nY\n>>>>>>> t\n"
    h = aimerge.parse_diff3(text).hunks[0]
    rules = _rules(tmp_path)
    failures = aiprompt.check_proposal([h], _choice(1, ["O1", "B2", "B1", "T1"], rules=["R1"]), rules)
    assert any("order" in f and "B" in f for f in failures)
    assert aiprompt.check_proposal([h], _choice(1, ["O1", "B1", "B2", "T1"], rules=["R1"]), rules) == []


def test_a_rewrite_at_exactly_the_threshold_needs_no_rule(tmp_path):
    """Mutation survivor M13: 'at or above' SUPERSEDE_RATIO, the same
    boundary aimerge and validate() use."""
    import difflib
    assert difflib.SequenceMatcher(None, "abcd", "abef").ratio() == aimerge.SUPERSEDE_RATIO
    h = aimerge.parse_diff3("<<<<<<< o\nabcd\n=======\nabef\n>>>>>>> t\n").hunks[0]
    assert aiprompt.check_proposal([h], _choice(1, ["O1"]), _none_rules(tmp_path)) == []


def test_duplicates_differing_only_in_indentation_are_duplicates(tmp_path):
    """Mutation survivor M4: the duplicate check compares stripped text, as
    the validator's known-line sets do."""
    h = aimerge.parse_diff3("<<<<<<< o\n  same\n=======\nsame\n>>>>>>> t\n").hunks[0]
    failures = aiprompt.check_proposal([h], _choice(1, ["O1", "T1"]), _none_rules(tmp_path))
    assert any("twice" in f for f in failures)


def test_one_failure_per_hunk_for_duplicates(tmp_path):
    """Mutation survivor M3: the first duplicate is reported and the check
    moves on, rather than one line per repetition."""
    h = aimerge.parse_diff3(DIFF3).hunks[0]
    failures = aiprompt.check_proposal([h], _choice(1, ["O1", "O2", "T1", "O2", "T1"]),
                                       _none_rules(tmp_path))
    assert sum("twice" in f for f in failures) == 1


def test_parse_response_keeps_the_first_answer_when_a_hunk_is_answered_twice():
    """Mutation survivor M15: the duplicate is refused, not applied over the
    first."""
    choices, failures = aiprompt.parse_response(
        {"hunks": [{"hunk": 1, "lines": ["O1"]}, {"hunk": 1, "lines": ["T1"]}]})
    assert failures and choices[1].lines == ["O1"]


def test_parse_response_rejects_a_boolean_hunk_number():
    """Mutation survivor M14: True is an int to isinstance, and not a hunk."""
    _, failures = aiprompt.parse_response({"hunks": [{"hunk": True, "lines": ["O1"]}]})
    assert failures


def test_two_digit_ids_keep_their_numeric_order(tmp_path):
    """Mutation survivor N4 (round 2): `O10` follows `O9`, not `O1`."""
    ours = "\n".join(f"line {k}" for k in range(1, 12))
    h = aimerge.parse_diff3(f"<<<<<<< o\n{ours}\n=======\nY\n>>>>>>> t\n").hunks[0]
    rules = _rules(tmp_path)
    ok = _choice(1, [f"O{k}" for k in range(1, 12)], rules=["R1"])
    assert aiprompt.check_proposal([h], ok, rules) == []
    bad = _choice(1, ["O10", "O9"], rules=["R1"])
    assert any("order" in f for f in aiprompt.check_proposal([h], bad, rules))


def test_base_text_the_payload_still_has_is_not_base_only(tmp_path):
    """Mutation survivor N7: 'base-only' means in neither O nor T."""
    text = "<<<<<<< o\nX\n||||||| b\nkept by the payload\n=======\nkept by the payload\nY\n>>>>>>> t\n"
    h = aimerge.parse_diff3(text).hunks[0]
    rules = _rules(tmp_path)
    # select the base's copy of the shared line rather than theirs' -- not a revival
    failures = aiprompt.check_proposal([h], _choice(1, ["O1", "B1", "T2"]), rules)
    assert not any("base-only" in f for f in failures)


def test_parse_failures_number_answers_from_one():
    """Mutation survivor N10: a person reading "answer 2 is not an object"
    counts from one, as the JSON they are looking at does."""
    _, failures = aiprompt.parse_response({"hunks": [{"hunk": 1, "lines": ["O1"]}, 7]})
    assert any("answer 2" in f for f in failures)


def test_failures_never_use_the_validators_loss_prefix(tmp_path):
    from dazzle_claude_config import merge
    h = aimerge.parse_diff3(DIFF3).hunks[0]
    failures = aiprompt.check_proposal([h], _choice(1, ["T2"]), _none_rules(tmp_path))
    assert failures
    assert all(f.startswith(aiprompt.PROPOSAL_PREFIX) for f in failures)
    assert not any(f.startswith(merge._LOSS_PREFIX) for f in failures)


def test_resolve_then_assemble_produces_the_file(tmp_path):
    parsed = aimerge.parse_diff3(DIFF3)
    choices = _choice(1, ["O1", "O2", "T2"])
    assert aiprompt.check_proposal(parsed.hunks, choices, _rules(tmp_path)) == []
    out = aimerge.assemble(parsed, aiprompt.resolve(parsed.hunks, choices))
    assert out == ("# Title\nshared intro\n"
                   "keep the services section verbatim\nboth sides have this line\n"
                   "install nginx and certbot before enabling the site\n"
                   "tail\n")
