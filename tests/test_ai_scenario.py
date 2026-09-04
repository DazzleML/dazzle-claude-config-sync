"""#19's acceptance criterion 7: the scenario the feature exists for.

A box whose `CLAUDE.md` forked from the payload a year ago. Three regions
both sides changed, and three different right answers in one file: keep
this box's own wording where a rule says the box owns it, take upstream's
wording where nothing does, and drop a section this box has no use for --
which only a rule may license, because dropping is the one thing the
check will not let a model do on its own judgement.

prompt-only and a canned answer, as the criterion asks: no backend runs,
nothing is installed, and the proposal is assembled by ccs from line ids.
The negative half is the point of the positive one -- the same answer
without the rule citation is refused, and the refusal names the line.
"""
from __future__ import annotations

import json

from dazzle_claude_config import airecord, aistep

# The payload a year ago. One line per paragraph, as this house writes.
BASE = b"""# Machine config

## Deletions
Confirm with the person before removing anything.

## Windows paths
Use PowerShell for junctions; cmd.exe fails silently from bash.

## Tests
Run the suite before you push.
"""

# The box: a Linux VPS. It rewrote the deletion rule its own way, rewrote
# the Windows section into something about its own paths, and rewrote the
# test line loosely.
OURS = b"""# Machine config

## Deletions
Confirm with the person, and stage the file to /var/backups first, before removing anything.

## Windows paths
Not applicable on this host; kept only so the section numbering matches the payload.

## Tests
Run the suite.
"""

# The payload today: a tighter deletion rule, a Windows section that grew,
# and a test line that names the command.
THEIRS = b"""# Machine config

## Deletions
Confirm with the person before removing anything, and record the confirmation in the receipt.

## Windows paths
Use PowerShell for junctions and symlinks; cmd.exe fails silently when invoked from bash.

## Tests
Run `python -m pytest -q` before you push.
"""

RULES = """\
Deletions on this host stage the file to /var/backups first. KEEP the deletion
wording this box has, whatever the payload says.

This host runs Linux. Sections that only describe Windows may be dropped
entirely rather than merged.

Everywhere else, prefer the payload's wording: it is the shared one.
"""
# R1 = keep our deletions wording, R2 = a Windows-only section may go,
# R3 = take theirs elsewhere.

ANSWER = {"hunks": [
    {"hunk": 1, "lines": ["O1"], "rules": ["R1"],
     "rationale": "this box stages deletions to /var/backups; R1 keeps its wording"},
    {"hunk": 2, "lines": [], "rules": ["R2"],
     "rationale": "a Linux host has no use for the Windows section; R2 lets it go"},
    {"hunk": 3, "lines": ["T1"], "rules": ["R3"],
     "rationale": "upstream names the command; R3 prefers the payload's wording here"},
]}
# Hunk 3 cites R3 rather than leaning on the rewrite exemption: the box's
# "Run the suite." and the payload's "Run `python -m pytest -q` before you
# push." share too little text to count as one line rewriting the other, so
# the check treats dropping the box's line as a drop. That is the rule
# working, and it is why R3 is in the rules file at all.


def _world(tmp_path):
    for name, data in (("ours", OURS), ("base", BASE), ("theirs", THEIRS)):
        (tmp_path / name).write_bytes(data)
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "_default.md").write_bytes(RULES.encode())
    ws = tmp_path / "ws"
    ws.mkdir()
    return dict(ours=tmp_path / "ours", base=tmp_path / "base", theirs=tmp_path / "theirs",
                merged=ws / "CLAUDE.md.merged", workdir=tmp_path / "work")


def _run(tmp_path, w, answer):
    p = tmp_path / "answer.json"
    p.write_text(json.dumps(answer), encoding="utf-8")
    opts = aistep.AiOptions(backend="prompt-only", rules_dir=tmp_path / "rules",
                            prompts_dir=tmp_path / "prompts", cache_dir=tmp_path / "cache",
                            response=p)
    return aistep.ai_step(label="CLAUDE.md", ours=w["ours"], base=w["base"], theirs=w["theirs"],
                          merged=w["merged"], opts=opts, workdir=w["workdir"])


def test_the_forked_box_resolves_three_ways_in_one_file(tmp_path):
    w = _world(tmp_path)
    out = _run(tmp_path, w, ANSWER)
    assert out.status == "proposed", out.failures
    assert out.hunks == 3
    text = out.proposal.read_text(encoding="utf-8")
    # kept, because a rule says this box owns the deletion wording
    assert "stage the file to /var/backups first" in text
    assert "record the confirmation in the receipt" not in text
    # dropped entirely: neither side's Windows paragraph survives
    assert "PowerShell" not in text and "Not applicable on this host" not in text
    assert "## Windows paths" in text          # the heading is context, not a hunk
    # taken from the payload, under the rule that prefers the shared wording
    assert "Run `python -m pytest -q` before you push." in text
    assert "Run the suite.\n" not in text
    assert "<<<<<<<" not in text
    # the rules file is named with its hash, and the rationales come back in order
    assert "_default.md" in out.rules and "(3 rules)" in out.rules
    assert [n for n, _, _ in out.rationales] == [1, 2, 3]
    assert [r for _, r, _ in out.rationales] == [["R1"], ["R2"], ["R3"]]
    rec = airecord.load(airecord.record_path(w["merged"]))
    assert rec is not None and rec.valid and rec.backend == "prompt-only"
    assert rec.rules_sha and rec.copied_sha == ""      # the step never copies


def test_the_same_drop_without_the_rule_is_refused_and_names_the_line(tmp_path):
    """The negative half: nothing but a cited rule licenses the drop."""
    w = _world(tmp_path)
    answer = json.loads(json.dumps(ANSWER))
    answer["hunks"][1]["rules"] = []                   # the same drop, uncited
    out = _run(tmp_path, w, answer)
    assert out.status == "rejected"
    assert any("hunk 2" in f and "dropped with no rule cited" in f for f in out.failures), out.failures
    assert all(f.startswith("proposal:") for f in out.failures)
    assert not airecord.proposal_path(w["merged"]).exists()
    rec = airecord.load(airecord.record_path(w["merged"]))
    assert rec is not None and rec.valid is False


def test_what_git_already_merged_is_never_sent(tmp_path):
    """#19's criterion 2, end to end: only the regions BOTH sides changed
    reach the model. A section the payload alone rewrote is merged by git
    and stays out of the prompt entirely -- not as a hunk, and (being far
    from one) not even as context. The model cannot weigh in on text
    nobody disagreed about, which is half of what keeps this safe."""
    far = "\n".join(f"filler {i}" for i in range(1, 9))
    base = (BASE.decode() + f"\n{far}\n\n## Logging\nOne line per request.\n").encode()
    ours = (OURS.decode() + f"\n{far}\n\n## Logging\nOne line per request.\n").encode()
    # only the payload touched Logging: git merges it, nobody conflicts
    theirs = (THEIRS.decode() + f"\n{far}\n\n## Logging\n"
              "One line per request, and the request id in every line.\n").encode()
    for name, data in (("ours", ours), ("base", base), ("theirs", theirs)):
        (tmp_path / name).write_bytes(data)
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "_default.md").write_bytes(RULES.encode())
    ws = tmp_path / "ws"
    ws.mkdir()
    opts = aistep.AiOptions(backend="prompt-only", rules_dir=tmp_path / "rules",
                            prompts_dir=tmp_path / "prompts", cache_dir=tmp_path / "cache")
    out = aistep.ai_step(label="CLAUDE.md", ours=tmp_path / "ours", base=tmp_path / "base",
                         theirs=tmp_path / "theirs", merged=ws / "CLAUDE.md.merged",
                         opts=opts, workdir=tmp_path / "work")
    assert out.status == "prompt-written" and out.hunks == 3      # the same three, no more
    text = out.prompt_path.read_text(encoding="utf-8")
    assert "the request id in every line" not in text
    assert "## Logging" not in text
    assert "/var/backups" in text                                  # the dual-touched region is there


def test_a_rule_that_is_not_in_the_file_cannot_license_anything(tmp_path):
    """R9 does not exist: the drop fails twice over, and both say so."""
    w = _world(tmp_path)
    answer = json.loads(json.dumps(ANSWER))
    answer["hunks"][1]["rules"] = ["R9"]
    out = _run(tmp_path, w, answer)
    assert out.status == "rejected"
    joined = " | ".join(out.failures)
    assert "cites rule R9" in joined and "dropped with no rule cited" in joined
