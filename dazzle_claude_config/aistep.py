"""One file through the AI step: paths in, a proposal and its record out.

This is the orchestration of ``ccs merge --ai`` for a single file, kept
apart from ``merge.py`` so it can be tested with three files and no
manifest, no checkout, no tool:

  1. the three-way merge itself (``git merge-file --diff3``) -- git has
     already classified: what it resolved is clean, every conflict hunk is
     a region both sides changed, and only those go to the model;
  2. the rules the person wrote, with their ids;
  3. the prompt, from the template;
  4. the answer -- from a file the person carried back (``--ai-response``),
     from the workspace (an answer placed beside the proposal), from the
     ``prompt-only`` floor (the prompt is written for them, nothing is
     answered), or from a backend through the facade, with a cache keyed
     on what the merge was made from;
  5. the check (``aiprompt.check_proposal``), then assembly, then
     ``<label>.merged-ai`` beside the person's ``.merged`` and the record
     beside that.

It never reads or writes ``.merged``, never installs anything, and never
imports ``merge.py``: the copy rule, the validator's backstop and the
report belong to the caller, which owns everything that can destroy or
install.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import aimerge, aiprompt, airecord, airules, basefind
from .seeddecisions import norm_sha

# `ailib` -- and through it the vendored library -- is imported INSIDE the
# two functions that need it, never here. This module is imported by
# `merge.py`, which is imported by `cli.py` at startup, so a module-level
# import would make every verb of ccs depend on the AI library being
# importable: a broken or missing vendored copy took the whole CLI down with
# a traceback before an argument was parsed, and `ccs doctor`'s "missing or
# broken" warning could never run. Found by the checklist sweep of
# 2026-09-05 (run-02, step 2.5).
#: The mode that sends nothing: the prompt is written for a person to carry.
#: A mode of the CALLER, so it is defined here; `ailib.PROMPT_ONLY` spells
#: the same string for the presets' side and a test pins the two equal.
PROMPT_ONLY = "prompt-only"
#: The cache namespace: two tools' fingerprints cannot collide.
TOOL_NAME = "ccs-merge"


@dataclass
class AiOptions:
    """What the CLI decided; one parameter into ``merge.run``.

    `backend` is a preset name (or prompt-only, the mode that sends
    nothing); `endpoint`, `model`, `api_key_env` and `api_key_file` override
    the preset's own values and are applied by `ailib.build_backend`;
    `keys_dir` is where a hosted preset's default key file lives
    (`<keys_dir>/<preset>.env`, read only when the environment has nothing).
    Nothing here knows which of them a given backend uses -- that is the
    preset's business.
    """
    rules_dir: Path
    prompts_dir: Path
    cache_dir: Path
    backend: str = PROMPT_ONLY
    refresh: bool = False          # --ai-refresh: bypass the cache
    verbose: bool = False          # --ai-verbose: stream the backend
    response: Path | None = None   # --ai-response FILE: an answer carried back
    timeout: int = 120
    endpoint: str | None = None    # override the preset's server address
    model: str | None = None       # override the preset's model
    api_key_env: str | None = None  # override the NAME of the credential's env var
    api_key_file: str | None = None  # a key file read before the environment (the PATH)
    keys_dir: Path | None = None   # `~/claude/keys`: the default key files, read after it


@dataclass(frozen=True)
class AiStep:
    """One step of an `--ai` plan (U4/U5 of #64): `recipe` -- the
    line-selection pass over the conflict hunks -- or `deep` -- the
    semantic pass over the whole file in a sandbox; `backend` is the preset
    it runs on."""
    kind: str
    backend: str


@dataclass
class AiOutcome:
    """What happened to one file, for the caller's report and record.

    The recipe's statuses: no-hunks | prompt-written | proposed | rejected |
    backend-failed. The deep step's (`kind == "deep"`): deep-proposed (a
    variant kept within the allowed rung) | deep-empty (the model changed
    nothing: a correct answer) | deep-failed (the edits reached beyond the
    allowed rung, or the answer could not be applied) | deep-skipped (no
    call was made: nothing to work on, the backend not ready, or a scope
    it cannot reach) | deep-escaped (the backend changed a REAL file; the
    variant is discarded).
    """
    status: str                    # no-hunks | prompt-written | proposed | rejected | backend-failed | deep-*
    hunks: int = 0                 # regions both sides changed: the model's
    clean_lines: int = 0           # lines git resolved on its own: never sent
    backend: str = ""              # the preset's name, as the person typed it
    backend_identity: str = ""     # what actually answered: transport, address, model
    model_used: str = ""           # the model the backend reports having used
    honoured: tuple[str, ...] = ()  # the request fields the backend enforced (schema, model...)
    rules: str = ""                # the rules line (path @ sha, or none)
    proposal: Path | None = None
    record: airecord.Record | None = None
    failures: list[str] = field(default_factory=list)
    rationales: list[tuple[int, list[str], str]] = field(default_factory=list)
    reports: list[str] = field(default_factory=list)   # the sub-line report lines
    # (hunk, the rules cited, the pane lines that citation let go) -- the
    # caller's file-level validator has no idea a rules file exists, and
    # without this it refuses exactly the drops the person pre-authorised.
    licensed: list[tuple[int, list[str], list[str]]] = field(default_factory=list)
    prompt_path: Path | None = None
    response_path: Path | None = None
    cached: bool = False
    error: str = ""
    error_path: Path | None = None   # the backend's full output, when it was long
    # -- the deep step (U4, #64) --------------------------------------------------
    kind: str = "recipe"           # recipe | deep
    variant: Path | None = None    # <label>.merged-ai.<n>: the deep step's answer, beside the others
    scope_allowed: int = 0         # the rung the person allowed (1-4)
    scope_needed: int = 0          # the rung the edits needed (0 = no edits)
    touched: list[str] = field(default_factory=list)   # sandbox paths the model changed
    # (path, region, rung, the model's reason) per edit -- the report's lines
    edits: list[tuple[str, str, int, str]] = field(default_factory=list)
    summary: str = ""              # the model's one-line summary of what it did
    guarantees: str = ""           # the guarantees line for this answer
    escapes: list[str] = field(default_factory=list)   # REAL files the backend changed (deep-escaped)
    tripwire: list[str] = field(default_factory=list)  # the loss check's lines: recorded, never the gate
    warning: str = ""              # the backend's readiness warning (#62)


def _safe(label: str) -> str:
    """The workspace's own transform: one file name per label, however
    deep the label; ``<stem>-<ts>`` alone collided on ``SKILL.md``."""
    return label.replace("/", "__").replace("\\", "__")


def _answer_data(text: str):
    """The JSON in an answer: the last fenced block, else the whole text."""
    from . import ailib
    data = ailib.parsers.json_block(text)
    if data is not None:
        return data
    try:
        return json.loads(text)
    except ValueError:
        return None


def ai_step(*, label: str, ours: Path, base: Path, theirs: Path, merged: Path,
            opts: AiOptions, workdir: Path, dossier: str = "",
            base_kind: str = "inferred", facts: dict | None = None) -> AiOutcome:
    """Run one file through the step. `merged` is the person's workspace
    file: never read, only the name the proposal, the record and the
    response file are placed beside. `facts` are the structured ancestry
    facts that join the cache key (the dossier prose does not: a reworded
    sentence must not flush every cache on every box)."""
    o, b, t = ours.read_bytes(), base.read_bytes(), theirs.read_bytes()
    merged_lines, rc = basefind.merge_file_diff3(
        basefind.lines_of(o), basefind.lines_of(b), basefind.lines_of(t), Path(workdir))
    if rc == 255:
        return AiOutcome("backend-failed", backend=opts.backend,
                         error="git merge-file failed on the three inputs")
    parsed = aimerge.parse_diff3("\n".join(merged_lines))
    if not parsed.hunks:
        return AiOutcome("no-hunks", backend=opts.backend)

    rules = airules.load_rules(label, opts.rules_dir)
    prompt = aiprompt.build_prompt(label, parsed.hunks, rules, dossier)
    out = AiOutcome("pending", hunks=len(parsed.hunks), backend=opts.backend,
                    clean_lines=sum(len(s.lines) for s in parsed.segments if s.kind == "clean"),
                    rules=rules.describe(),
                    reports=[l for h in parsed.hunks for l in aimerge.sub_line_report(h)],
                    response_path=airecord.response_path(merged))
    proposal_path = airecord.proposal_path(merged)
    record_path = airecord.record_path(merged)

    # What the proposal was made FROM, on this side of the seam: the three
    # sides, the rules, how the base was chosen, the structured ancestry
    # facts. Nothing about the backend -- which model, which server -- is
    # here, because the backend supplies its own identity to the cache key
    # (`run()` below) and this file never has to know which of those facts
    # matter for which transport. For an answer that never went through a
    # backend (a file carried back, or prompt-only) the record's
    # fingerprint is the hash of these inputs alone.
    fingerprint = {"base": norm_sha(b), "ours": norm_sha(o), "theirs": norm_sha(t),
                   "rules": rules.sha, "base_kind": base_kind, **(facts or {})}
    key = hashlib.sha256(json.dumps(fingerprint, sort_keys=True, default=str)
                         .encode("utf-8")).hexdigest()[:16]

    # -- the answer ------------------------------------------------------------
    answer: str | None = None
    if opts.response is not None:
        answer = Path(opts.response).read_text(encoding="utf-8-sig")
        out.response_path.parent.mkdir(parents=True, exist_ok=True)
        out.response_path.write_text(answer, encoding="utf-8")   # kept beside the proposal
    elif out.response_path.is_file():
        answer = out.response_path.read_text(encoding="utf-8-sig")
    elif opts.backend == PROMPT_ONLY:
        opts.prompts_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = opts.prompts_dir / f"{_safe(label)}-{stamp}.md"
        path.write_text(prompt, encoding="utf-8")
        out.status = "prompt-written"
        out.prompt_path = path
        return out
    else:
        # One vocabulary for every backend: build it from the preset and the
        # person's overrides, ask whether it is ready, ask the question
        # through the cache. Which transport, which address, which model --
        # none of that is this file's business; the backend's own identity
        # goes into the cache key and the record.
        from . import ailib
        backend = ailib.build_backend(opts)
        ready = backend.probe()
        if not ready.ok:
            out.status = "backend-failed"
            out.error = f"backend {opts.backend!r} is not available ({ready.reason})"
            return out
        out.backend_identity = backend.identity
        req = ailib.Request(prompt=prompt, schema=aiprompt.ANSWER_SCHEMA, timeout=opts.timeout,
                            stream_to=sys.stdout if opts.verbose else None)
        resp = ailib.run(backend, req, cache_dir=opts.cache_dir, fingerprint_extra=fingerprint,
                         refresh=opts.refresh, tool=TOOL_NAME)
        key = resp.key or key
        out.cached, out.model_used, out.honoured = resp.cached, resp.model_used, resp.honoured
        if not resp.ok:
            out.status = "backend-failed"
            # A CLI's failure message is whatever IT chose to print, and that
            # can be enormous: a codex version mismatch put 268 KB of its own
            # model catalogue on the terminal here, twice, burying the one
            # line that said what went wrong. Keep it all -- it is the only
            # evidence there is -- but keep it in a file, and let the report
            # show the head of it.
            out.error = resp.error
            try:
                workdir.mkdir(parents=True, exist_ok=True)
                ep = workdir / "backend-error.txt"
                ep.write_text(resp.error, encoding="utf-8")
                out.error_path = ep
            except OSError:
                pass
            return out
        answer = resp.text

    # -- the check -------------------------------------------------------------
    data = _answer_data(answer)
    if data is None:
        choices, failures = {}, [f"{aiprompt.PROPOSAL_PREFIX} no JSON answer found "
                                 f"(expected one fenced ```json block, or a JSON file)"]
    else:
        choices, failures = aiprompt.parse_response(data)
        if not failures:
            failures = aiprompt.check_proposal(parsed.hunks, choices, rules)
    common = dict(ours=o, theirs=t, base=b, base_kind=base_kind, backend=opts.backend,
                  rules_path=str(rules.path or ""), rules_sha=rules.sha, fingerprint=key,
                  identity=out.backend_identity, model_used=out.model_used, honoured=out.honoured)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    if failures:
        rec = airecord.new_record(proposal=b"", valid=False, failures=failures, **common)
        airecord.write(record_path, rec)
        out.status = "rejected"
        out.failures = failures
        out.record = rec
        return out

    # -- the proposal ----------------------------------------------------------
    blob = aimerge.assemble(parsed, aiprompt.resolve(parsed.hunks, choices)).encode("utf-8")
    proposal_path.write_bytes(blob)
    licensed = _licensed_drops(parsed.hunks, choices)
    rec = airecord.new_record(proposal=blob, valid=True, failures=[],
                              licensed=[ln for _, _, lines in licensed for ln in lines],
                              **common)
    airecord.write(record_path, rec)
    out.status = "proposed"
    out.proposal = proposal_path
    out.record = rec
    out.rationales = [(n, list(c.rules), c.rationale) for n, c in sorted(choices.items())]
    out.licensed = licensed
    return out


def _licensed_drops(hunks, choices) -> list[tuple[int, list[str], list[str]]]:
    """Per hunk: the rules the answer cited, and the pane lines that citation
    let go.

    `check_proposal` has already ruled on these -- it passed, so every id
    exists and every drop is either a rewrite or licensed by a rule that is
    in the loaded file. What this list is for is the layer above: the
    caller's `validate` reads the assembled file against the two sides and
    knows nothing about rules, so a drop the person pre-authorised in their
    own words looks to it exactly like content lost by accident. Measured on
    a scratch world (2026-09-04): `--dissimilar`, a rules file, `R2` cited on
    the hunk -- the answer passed the check and the file was refused anyway,
    which made the rules file decorative for the one thing it is for.
    """
    out: list[tuple[int, list[str], list[str]]] = []
    for h in hunks:
        c = choices.get(h.n)
        if c is None or not c.rules:
            continue
        table = h.ids()
        kept = {table[i].strip() for i in c.lines if i in table}
        gone = [ln for ln in list(h.ours) + list(h.theirs)
                if ln.strip() and ln.strip() not in kept]
        if gone:
            out.append((h.n, list(c.rules), gone))
    return out
