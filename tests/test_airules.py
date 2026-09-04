"""a3 -- the rules a person wrote for `ccs merge --ai`, loaded and named.

Rules are plain prose in user territory: one file per path
(`~/claude/ccs-merge-rules/<label>.md`), else `_default.md`, else none --
and "none" is a named degradation that the output says out loud, never a
crash. Each non-blank paragraph gets a positional id (`R1`, `R2`, ...) so
a model can cite the rule that licenses a drop and ccs can check the
citation mechanically: the id exists in the file whose hash is printed.
"""
from __future__ import annotations

import hashlib

from dazzle_claude_config import airules

RULES = (
    "# Rules for dotclaude/CLAUDE.md on this box\n"
    "\n"
    "This box is a production Linux server. KEEP verbatim: the sections\n"
    "\"Services & Configuration\" and \"Port Allocation\".\n"
    "\n"
    "TAKE upstream's wording everywhere else.\n"
    "\n"
    "\n"
    "NEVER introduce Windows paths or the Dazzle command shell section.\n"
)


def _write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_per_path_file_wins_over_default(tmp_path):
    _write(tmp_path / "dotclaude" / "CLAUDE.md.md", RULES)
    _write(tmp_path / "_default.md", "TAKE upstream everywhere.\n")
    r = airules.load_rules("dotclaude/CLAUDE.md", tmp_path)
    assert r.source == "path"
    assert r.path == tmp_path / "dotclaude" / "CLAUDE.md.md"
    assert list(r.ids) == ["R1", "R2", "R3"]
    assert r.ids["R1"].startswith("This box is a production Linux server.")
    assert r.ids["R2"] == "TAKE upstream's wording everywhere else."
    assert r.ids["R3"].startswith("NEVER introduce Windows paths")
    assert r.looked == tuple(airules.candidates("dotclaude/CLAUDE.md", tmp_path))   # N6


def test_blank_paragraphs_and_whitespace_lines_take_no_id():
    """Mutation survivors N1/N2 (round 2): leading or trailing blank
    paragraphs do not shift the numbering, a whitespace-only text has no
    rules, and a whitespace-only last line is not part of the rule."""
    assert airules.split_rules("\n\n  \n\nrule one\n\n\n") == {"R1": "rule one"}
    assert airules.split_rules("   \n") == {}
    assert airules.split_rules("rule\n   ") == {"R1": "rule"}
    # indentation inside a rule is the person's and stays
    assert airules.split_rules("  - keep this\n  - and this\n") == {"R1": "  - keep this\n  - and this"}


def test_an_indented_heading_is_still_a_heading():
    """Mutation survivor N3: `#` after leading spaces is a heading too."""
    assert airules.split_rules("  # indented heading\n\nrule\n") == {"R1": "rule"}


def test_a_directory_where_the_rules_file_should_be_is_not_a_file(tmp_path):
    """Mutation survivor N5: `exists()` would accept a directory and crash on
    read; `is_file()` falls through to the next candidate."""
    (tmp_path / "_default.md").mkdir()
    r = airules.load_rules("x", tmp_path)
    assert r.source == "none"


def test_undecodable_bytes_do_not_crash_the_load(tmp_path):
    """Mutation survivor N8: a rules file with a stray non-UTF-8 byte is
    still loaded; the bad byte is replaced, never fatal."""
    (tmp_path / "_default.md").write_bytes(b"KEEP the \xff section.\n")
    r = airules.load_rules("x", tmp_path)
    assert r.source == "default" and list(r.ids) == ["R1"] and "KEEP the" in r.ids["R1"]


def test_default_file_is_the_fallback_and_says_so(tmp_path):
    _write(tmp_path / "_default.md", "TAKE upstream everywhere.\n")
    r = airules.load_rules("dotclaude/CLAUDE.md", tmp_path)
    assert r.source == "default"
    assert r.path == tmp_path / "_default.md"
    assert r.ids == {"R1": "TAKE upstream everywhere."}
    assert "_default.md" in r.describe()


def test_no_file_is_a_named_degradation_not_a_crash(tmp_path):
    r = airules.load_rules("dotclaude/CLAUDE.md", tmp_path)
    assert r.source == "none" and r.path is None and r.ids == {} and r.sha == ""
    d = r.describe()
    assert "none" in d
    assert "CLAUDE.md.md" in d and "_default.md" in d   # where it looked
    assert " or " in d                                   # N7: "at A or B", the designed sentence


def test_headings_are_structure_not_rules():
    ids = airules.split_rules("# Heading\n\nrule one\n\n## Another\n\nrule two\nstill rule two\n")
    assert ids == {"R1": "rule one", "R2": "rule two\nstill rule two"}


def test_sha_is_over_lf_normalised_bytes_and_shown_short(tmp_path):
    (tmp_path / "_default.md").write_bytes(b"a\r\nb\r\n")   # bytes: no newline translation
    r = airules.load_rules("x", tmp_path)
    assert r.sha == hashlib.sha256(b"a\nb\n").hexdigest()
    assert r.sha[:7] in r.describe()
    assert "(1 rule)" in r.describe()


def test_describe_shows_a_seven_character_hash_like_git(tmp_path):
    """Mutation survivor M1 (v0.5.21 sweep): the short hash is git's seven
    characters, the same length every other ccs line uses for a sha."""
    import re
    (tmp_path / "_default.md").write_bytes(b"rule\n")
    d = airules.load_rules("x", tmp_path).describe()
    assert re.search(r" @ [0-9a-f]{7} \(", d), d


def test_a_headings_only_file_has_zero_rules_and_says_so(tmp_path):
    """Mutation survivor M2: zero is plural."""
    (tmp_path / "_default.md").write_bytes(b"# only a heading\n\n## and another\n")
    r = airules.load_rules("x", tmp_path)
    assert r.ids == {}
    assert "(0 rules)" in r.describe()


def test_a_bom_never_leaks_into_the_first_rule(tmp_path):
    """Mutation survivor M6: Windows editors write a UTF-8 BOM; the first
    rule must not begin with U+FEFF, or a citation of R1 shows garbage."""
    (tmp_path / "_default.md").write_bytes(b"\xef\xbb\xbfKEEP the services section.\n")
    r = airules.load_rules("x", tmp_path)
    assert r.ids == {"R1": "KEEP the services section."}


def test_a_paragraph_mixing_a_hash_line_with_prose_is_a_rule():
    """Mutation survivor M7: only a paragraph made ENTIRELY of # lines is a
    heading; a rule that starts with a commented label keeps its text."""
    ids = airules.split_rules("# services\nKEEP the services section verbatim.\n\n# heading only\n")
    assert ids == {"R1": "# services\nKEEP the services section verbatim."}


def test_trailing_whitespace_is_not_part_of_a_rule():
    """Mutation survivor M9: a rule's text is what a person reads, and
    trailing spaces would make two identical rules hash and cite apart."""
    assert airules.split_rules("KEEP this.   \nand this.\t\n") == {"R1": "KEEP this.\nand this."}


def test_rules_dir_and_prompts_dir_live_in_user_territory(tmp_path):
    assert airules.rules_dir(tmp_path) == tmp_path / "ccs-merge-rules"
    assert airules.prompts_dir(tmp_path) == tmp_path / "ccs-merge-rules" / "_prompts"


def test_candidates_are_the_per_path_file_then_default(tmp_path):
    assert airules.candidates("skills/think/SKILL.md", tmp_path) == [
        tmp_path / "skills" / "think" / "SKILL.md.md", tmp_path / "_default.md"]
