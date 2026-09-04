"""a5b -- the provenance record beside an AI proposal.

"Identical bytes mean the AI wrote it" is an inference, and the same shape
as the one the recorded sync point (#14) replaces. So the fact is written
down: when `--ai` writes a proposal, and again when it copies that
proposal into a missing `.merged`, a small JSON record beside the files
says what was written, from which sides, under which rules, by which
backend, and whether validation passed. Everything the display says about
provenance is read from this record; the bytes are only the signal.

Workspace-scoped and throwaway: it dies with the workspace, unlike #14's
durable record, and it is never a schema #14 must live with.
"""
from __future__ import annotations

import json
from pathlib import Path

from dazzle_claude_config import airecord
from dazzle_claude_config.seeddecisions import norm_sha


def _rec(**over):
    base = dict(proposal_sha="p" * 64, ours_sha=norm_sha(b"ours\n"), theirs_sha=norm_sha(b"theirs\n"),
                base_sha="b" * 64, base_kind="inferred", backend="prompt-only",
                rules_path="", rules_sha="", fingerprint="f" * 16, valid=True, failures=[])
    base.update(over)
    return airecord.Record(**base)


def test_the_three_files_beside_a_merged_file(tmp_path):
    merged = tmp_path / "skills__think__SKILL.md.merged"
    assert airecord.proposal_path(merged) == tmp_path / "skills__think__SKILL.md.merged-ai"
    assert airecord.record_path(merged) == tmp_path / "skills__think__SKILL.md.merged-ai.record.json"
    assert airecord.response_path(merged) == tmp_path / "skills__think__SKILL.md.merged-ai.response.json"


def test_write_then_load_round_trips_every_field(tmp_path):
    p = tmp_path / "x.merged-ai.record.json"
    r = _rec(failures=["proposal: hunk 1 drops O2 with no rule"], valid=False)
    airecord.write(p, r)
    got = airecord.load(p)
    assert got == r
    assert got.version == 1 and got.origin == "ai"
    assert got.created and got.copied_sha == "" and got.accepted_unchanged == ""
    # hand-editable: flat JSON, one object, indented
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["origin"] == "ai" and data["backend"] == "prompt-only"


def test_load_treats_absent_or_malformed_as_no_record(tmp_path):
    p = tmp_path / "x.merged-ai.record.json"
    assert airecord.load(p) is None
    p.write_text("{not json", encoding="utf-8")
    assert airecord.load(p) is None
    p.write_text("[1, 2]", encoding="utf-8")
    assert airecord.load(p) is None
    p.write_text(json.dumps({"version": 1, "origin": "ai"}), encoding="utf-8")   # fields missing
    assert airecord.load(p) is None
    p.write_text(json.dumps({"version": 2, "origin": "ai"}), encoding="utf-8")   # a future schema
    assert airecord.load(p) is None


def test_write_is_atomic_and_leaves_no_temp_file(tmp_path):
    p = tmp_path / "x.merged-ai.record.json"
    airecord.write(p, _rec())
    assert [q.name for q in tmp_path.iterdir()] == [p.name]


def test_a_failed_write_leaves_the_previous_record_intact(tmp_path, monkeypatch):
    """Mutation survivor M10 (v0.5.21 sweep): an in-place write truncates
    the record before the failure; the atomic shape leaves the old one."""
    p = tmp_path / "x.merged-ai.record.json"
    before = _rec(backend="claude")
    airecord.write(p, before)

    def boom(*a, **k):
        raise RuntimeError("disk says no")
    monkeypatch.setattr(airecord.json, "dump", boom)
    import pytest
    with pytest.raises(RuntimeError):
        airecord.write(p, _rec(backend="codex"))
    monkeypatch.undo()
    assert airecord.load(p) == before
    assert [q.name for q in tmp_path.iterdir()] == [p.name]   # no .tmp left behind


def _full_json(**over):
    from dataclasses import asdict
    d = json.loads(json.dumps(asdict(_rec())))
    d.update(over)
    return d


def test_load_rejects_a_record_with_a_required_field_missing_or_mistyped(tmp_path):
    """Mutation survivors M6/M8/M9: every required key, the schema version,
    and the types of the two fields the display branches on are checked."""
    p = tmp_path / "x.merged-ai.record.json"
    full = _full_json()
    p.write_text(json.dumps(full), encoding="utf-8")
    assert airecord.load(p) is not None                       # the control
    for missing in ("failures", "created", "backend"):
        d = dict(full); del d[missing]
        p.write_text(json.dumps(d), encoding="utf-8")
        assert airecord.load(p) is None, missing
    p.write_text(json.dumps(_full_json(version=2)), encoding="utf-8")
    assert airecord.load(p) is None
    p.write_text(json.dumps(_full_json(valid="yes")), encoding="utf-8")
    assert airecord.load(p) is None
    p.write_text(json.dumps(_full_json(failures="none")), encoding="utf-8")
    assert airecord.load(p) is None


def test_a_loaded_record_keeps_its_original_timestamp(tmp_path):
    """Mutation survivor N2 (round 2): `created` is stamped only when
    absent; a record read back tomorrow still says when it was made."""
    p = tmp_path / "x.merged-ai.record.json"
    p.write_text(json.dumps(_full_json(created="2020-01-02T03:04:05+00:00")), encoding="utf-8")
    assert airecord.load(p).created == "2020-01-02T03:04:05+00:00"


def test_new_record_copies_the_failures_list():
    """Mutation survivor N4: the caller's list is not aliased."""
    failures = ["proposal: hunk 1: O2 dropped with no rule"]
    r = airecord.new_record(proposal=b"p", ours=b"o", theirs=b"t", base=None, base_kind="none",
                            backend="claude", rules_path="", rules_sha="", fingerprint="",
                            valid=False, failures=failures)
    failures.append("later")
    assert r.failures == ["proposal: hunk 1: O2 dropped with no rule"]


def test_load_tolerates_an_unknown_key_and_a_bom(tmp_path):
    """Mutation survivors N6/N7: the record is hand-editable, so a note a
    person added must not turn it into "no record", and an editor that
    writes a UTF-8 BOM must not either."""
    p = tmp_path / "x.merged-ai.record.json"
    p.write_text(json.dumps(_full_json(note="I read this one")), encoding="utf-8")
    assert airecord.load(p) is not None
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps(_full_json()).encode("utf-8"))
    assert airecord.load(p) is not None


def test_write_overwrites_an_existing_record_and_ends_with_a_newline(tmp_path):
    """Mutation survivor N8: `os.replace`, not `os.rename` (which refuses to
    overwrite on Windows); and a trailing newline, as every other record
    file in ccs has."""
    p = tmp_path / "x.merged-ai.record.json"
    airecord.write(p, _rec(backend="claude"))
    airecord.write(p, _rec(backend="codex"))          # the second write must succeed
    assert airecord.load(p).backend == "codex"
    assert p.read_bytes().endswith(b"\n")


def test_new_record_hashes_an_empty_base_rather_than_recording_none():
    """Mutation survivor M4: an empty base FILE is a fact with a hash;
    only an absent base records ""."""
    r = airecord.new_record(proposal=b"p", ours=b"o", theirs=b"t", base=b"", base_kind="supplied",
                            backend="claude", rules_path="", rules_sha="", fingerprint="",
                            valid=True, failures=[])
    assert r.base_sha == norm_sha(b"") and r.base_sha != ""


def test_mark_copied_is_set_once_and_never_rewritten():
    r = _rec()
    assert r.copied_sha == ""
    assert r.mark_copied(b"first\n") is True
    first = r.copied_sha
    assert first == norm_sha(b"first\n")
    assert r.mark_copied(b"second\n") is False
    assert r.copied_sha == first


def test_state_reads_the_bytes_against_the_copy_not_the_proposal():
    r = _rec(proposal_sha=norm_sha(b"new proposal\n"))
    assert airecord.state(r, b"anything") == "not-copied"
    r.mark_copied(b"copied\r\n")
    assert airecord.state(r, b"copied\n") == "unchanged"          # CRLF-insensitive
    assert airecord.state(r, b"copied\nplus an edit\n") == "edited"
    # a second --ai run rewrote proposal_sha; the person's edits that happen
    # to equal the NEW proposal are still theirs, not "unchanged"
    assert airecord.state(r, b"new proposal\n") == "edited"


def test_stale_sides_names_the_side_that_moved_since_the_proposal():
    r = _rec()
    assert airecord.stale_sides(r, b"ours\n", b"theirs\n") == []
    assert airecord.stale_sides(r, b"ours edited\n", b"theirs\n") == ["your live file"]
    assert airecord.stale_sides(r, b"ours\n", b"theirs moved\n") == ["the payload's copy"]
    assert airecord.stale_sides(r, b"x", b"y") == ["your live file", "the payload's copy"]


def test_new_record_stamps_created_and_hashes_the_sides():
    r = airecord.new_record(proposal=b"p\n", ours=b"o\r\n", theirs=b"t\n", base=b"b\n",
                            base_kind="inferred", backend="claude", rules_path="r.md",
                            rules_sha="c" * 64, fingerprint="f" * 16, valid=True, failures=[])
    assert r.proposal_sha == norm_sha(b"p\n") and r.ours_sha == norm_sha(b"o\n")
    assert r.theirs_sha == norm_sha(b"t\n") and r.base_sha == norm_sha(b"b\n")
    assert r.created[:4].isdigit() and "T" in r.created
    assert r.copied_sha == ""


def test_new_record_without_a_base_records_none():
    r = airecord.new_record(proposal=b"p", ours=b"o", theirs=b"t", base=None, base_kind="none",
                            backend="codex", rules_path="", rules_sha="", fingerprint="", valid=False,
                            failures=["refused: no base"])
    assert r.base_sha == "" and r.base_kind == "none"
