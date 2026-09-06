"""The provenance record beside an AI proposal.

``ccs merge --ai`` writes its proposal to ``<label>.merged-ai``, beside the
person's ``<label>.merged`` and never over it; when no ``.merged`` exists
it copies the proposal there so the diff tool and ``--accept`` have their
file. Two identical files make the provenance visible -- and "identical
bytes mean the AI wrote it" is an inference, the same shape as the one the
recorded sync point (#14) replaces, wrong in both directions the day the
person edits the copy back to the proposal or a second run writes a new
one. So the FACT is written here, at the moment it happens, and the
display reads the record; the bytes are only the signal.

Schema (``<label>.merged-ai.record.json``, flat, hand-editable, one object):

    version, origin ("ai"),
    proposal_sha       -- what is in .merged-ai (rewritten by every run)
    copied_sha         -- what was copied into .merged (set ONCE, never rewritten;
                          the resume branch reads this, not proposal_sha)
    ours_sha, theirs_sha, base_sha, base_kind   -- the sides the proposal was made from
    backend, rules_path, rules_sha, fingerprint  -- how it was made
    valid, failures    -- what validation said
    created            -- when
    accepted_unchanged -- the date of a `y` to the "unreviewed proposal" question

Every sha is over LF-normalised bytes (``seeddecisions.norm_sha``), because
live files on Windows are CRLF and the workspace is LF. A malformed or
foreign-version record reads as no record -- lost to corruption, never
widened by it. Workspace-scoped and throwaway: it dies with the workspace,
unlike #14's durable record, and it is never a schema #14 must live with.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path

from .seeddecisions import norm_sha

#: Schema 2 (2026-09-05): a record holds N answers and says which one is
#: chosen, so a future run that asks several backends at once (`--ai a,b`)
#: needs no migration of files already in people's workspaces -- a record on
#: disk is the expensive thing to change later. Today N is always one.
VERSION = 2
ORIGIN = "ai"
PROPOSAL_SUFFIX = "-ai"
RECORD_SUFFIX = "-ai.record.json"
RESPONSE_SUFFIX = "-ai.response.json"

#: The sides a proposal was made from, as the display names them.
OURS_NAME = "your live file"
THEIRS_NAME = "the payload's copy"


def proposal_path(merged: Path, n: int = 0) -> Path:
    """``<label>.merged-ai`` -- the proposal, beside the person's file.

    `n` names a further answer's proposal, ``<label>.merged-ai.<n>``, for
    the day a run asks several backends; nothing produces one yet, and the
    chosen answer is always the bare name."""
    return merged.with_name(merged.name + PROPOSAL_SUFFIX + (f".{n}" if n else ""))


def record_path(merged: Path) -> Path:
    """``<label>.merged-ai.record.json`` -- this record."""
    return merged.with_name(merged.name + RECORD_SUFFIX)


def response_path(merged: Path) -> Path:
    """``<label>.merged-ai.response.json`` -- where a carried-elsewhere
    answer is placed for ``--ai`` to apply."""
    return merged.with_name(merged.name + RESPONSE_SUFFIX)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class Record:
    proposal_sha: str
    ours_sha: str
    theirs_sha: str
    base_sha: str
    base_kind: str              # inferred | supplied | sibling | none
    backend: str
    rules_path: str             # "" when no rules file was found
    rules_sha: str
    fingerprint: str            # the cache key the proposal was made under
    valid: bool
    failures: list[str] = field(default_factory=list)
    # Lines a cited rule let the answer drop. They live here, not only in the
    # run that made them, because the file-level validator reads the result
    # against the two sides every time the file is looked at -- and a drop the
    # person authorised in their own rules file must not turn into a refusal
    # the next morning. An older record simply has none: a default, not a
    # required key, so `load` needs no version bump.
    licensed: list[str] = field(default_factory=list)
    created: str = ""
    copied_sha: str = ""
    accepted_unchanged: str = ""
    version: int = VERSION
    origin: str = ORIGIN
    # Every answer this record knows, and which one the proposal beside it
    # is. `backend` and `fingerprint` above stay as the chosen answer's name
    # and key, denormalised for a reader of the JSON and for the display.
    # Each answer: backend (the preset name), identity (transport, address,
    # model -- what actually answered), model_used, honoured (the request
    # fields the backend enforced), fingerprint, proposal_sha, created.
    answers: list[dict] = field(default_factory=list)
    chosen: int = 0

    def __post_init__(self) -> None:
        if not self.created:
            self.created = _now()
        if not self.answers:
            self.answers = [{"backend": self.backend, "identity": "", "model_used": "",
                             "honoured": [], "fingerprint": self.fingerprint,
                             "proposal_sha": self.proposal_sha, "created": self.created}]
            self.chosen = 0

    @property
    def answer(self) -> dict:
        """The chosen answer."""
        return self.answers[self.chosen] if self.answers else {}

    def mark_copied(self, data: bytes) -> bool:
        """Record what was copied into ``.merged``. Once: a later run that
        rewrites the proposal must not relabel the person's file, so the
        first copy's hash is the one the resume branch keeps reading."""
        if self.copied_sha:
            return False
        self.copied_sha = norm_sha(data)
        return True


def new_record(*, proposal: bytes, ours: bytes, theirs: bytes, base: bytes | None,
               base_kind: str, backend: str, rules_path: str, rules_sha: str,
               fingerprint: str, valid: bool, failures: list[str],
               licensed: list[str] = (), identity: str = "", model_used: str = "",
               honoured: tuple[str, ...] | list[str] = ()) -> Record:
    """A record for a proposal just written, hashing the sides it came from.
    `identity`, `model_used` and `honoured` are what the backend reported
    about itself; they go into the chosen answer, never into the key."""
    rec = Record(proposal_sha=norm_sha(proposal), ours_sha=norm_sha(ours),
                 theirs_sha=norm_sha(theirs),
                 base_sha=norm_sha(base) if base is not None else "",
                 base_kind=base_kind, backend=backend, rules_path=rules_path,
                 rules_sha=rules_sha, fingerprint=fingerprint, valid=valid,
                 failures=list(failures), licensed=list(licensed))
    rec.answers[0].update(identity=identity, model_used=model_used, honoured=list(honoured))
    return rec


_REQUIRED = ("proposal_sha", "ours_sha", "theirs_sha", "base_sha", "base_kind",
             "backend", "rules_path", "rules_sha", "fingerprint", "valid",
             "failures", "created")


def load(path: Path) -> Record | None:
    """The record at `path`, or None for absent, unreadable, malformed, or
    another schema version -- never a partial one.

    A schema-1 record (one backend, no `answers`) loads as schema 2 with its
    single answer filled in from the top-level fields, and is written back
    as 2 the next time it is written. One-way, on purpose.
    COMPAT(remove-after: one release with v2 records in the wild)
    """
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") not in (1, VERSION) \
            or data.get("origin") != ORIGIN:
        return None
    if data.get("version") == 1:
        data = {k: v for k, v in data.items() if k not in ("answers", "chosen")}
        data["version"] = VERSION
    if any(k not in data for k in _REQUIRED):
        return None
    if not isinstance(data["failures"], list) or not isinstance(data["valid"], bool):
        return None
    known = {f.name for f in fields(Record)}
    try:
        return Record(**{k: v for k, v in data.items() if k in known})
    except TypeError:
        return None


def write(path: Path, record: Record) -> None:
    """Atomic: written beside, then renamed over. (The shape of
    seeddecisions._write.)"""
    body = asdict(record)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(body, f, indent=1)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def state(record: Record, merged: bytes) -> str:
    """What ``.merged`` is, read against the COPY, never the proposal:
    ``not-copied`` (the proposal was never put there), ``unchanged`` (the
    bytes are still the copy's), ``edited`` (anything else -- the person's,
    whatever they now equal)."""
    if not record.copied_sha:
        return "not-copied"
    return "unchanged" if norm_sha(merged) == record.copied_sha else "edited"


def stale_sides(record: Record, ours: bytes, theirs: bytes) -> list[str]:
    """The sides that moved since the proposal was made, by the display's
    names -- an unchanged proposal made from yesterday's sides is not one to
    install today."""
    out: list[str] = []
    if norm_sha(ours) != record.ours_sha:
        out.append(OURS_NAME)
    if norm_sha(theirs) != record.theirs_sha:
        out.append(THEIRS_NAME)
    return out
