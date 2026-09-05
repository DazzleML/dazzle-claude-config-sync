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

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import ailib, aimerge, aiprompt, airecord, airules, basefind
from .seeddecisions import norm_sha

PROMPT_ONLY = ailib.PROMPT_ONLY
#: The cache namespace: two tools' fingerprints cannot collide.
TOOL_NAME = "ccs-merge"


@dataclass
class AiOptions:
    """What the CLI decided; one parameter into ``merge.run``."""
    rules_dir: Path
    prompts_dir: Path
    cache_dir: Path
    backend: str = PROMPT_ONLY
    refresh: bool = False          # --ai-refresh: bypass the cache
    verbose: bool = False          # --ai-verbose: stream the backend
    response: Path | None = None   # --ai-response FILE: an answer carried back
    timeout: int = 120
    endpoint: str | None = None    # lmstudio: the OpenAI-compatible server
    model: str | None = None       # lmstudio: the model id to pin, "" = whatever is loaded


@dataclass
class AiOutcome:
    """What happened to one file, for the caller's report and record."""
    status: str                    # no-hunks | prompt-written | proposed | rejected | backend-failed
    hunks: int = 0
    backend: str = ""
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


def _safe(label: str) -> str:
    """The workspace's own transform: one file name per label, however
    deep the label; ``<stem>-<ts>`` alone collided on ``SKILL.md``."""
    return label.replace("/", "__").replace("\\", "__")


def _answer_data(text: str):
    """The JSON in an answer: the last fenced block, else the whole text."""
    data = ailib.parse_json_block(text)
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
                    rules=rules.describe(),
                    reports=[l for h in parsed.hunks for l in aimerge.sub_line_report(h)],
                    response_path=airecord.response_path(merged))
    proposal_path = airecord.proposal_path(merged)
    record_path = airecord.record_path(merged)

    fingerprint = {"base": norm_sha(b), "ours": norm_sha(o), "theirs": norm_sha(t),
                   "rules": rules.sha, "base_kind": base_kind, **(facts or {})}
    if opts.backend == ailib.LMSTUDIO:
        # The backend name alone identifies a CLI, but not a local server:
        # one endpoint serves many models, and two models are two answerers.
        # Without this, swapping the model returns the previous one's answer
        # from cache and the person concludes the model ignored them.
        fingerprint["endpoint"] = opts.endpoint or ""
        fingerprint["model"] = opts.model or ""
    key = ailib.cache_key(fingerprint, opts.backend, TOOL_NAME)

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
        if opts.backend == ailib.LMSTUDIO:
            # A server-shaped backend is told where to look before it is
            # asked whether it is there; the CLI ones discover themselves.
            ailib.set_local(opts.endpoint, opts.model)
        if not ailib.check_available(opts.backend):
            out.status = "backend-failed"
            out.error = (f"backend {opts.backend!r} is not available "
                         + (f"({ailib.local_describe()})" if opts.backend == ailib.LMSTUDIO
                            else "(its CLI was not found)"))
            return out
        if not opts.refresh:
            hit = ailib.cache_read(key, opts.backend, opts.cache_dir)
            if hit and hit.get("raw_response"):
                answer = hit["raw_response"]
                out.cached = True
        if answer is None:
            ok, text = ailib.invoke(opts.backend, prompt, verbose=opts.verbose,
                                    timeout=opts.timeout)
            if not ok:
                out.status = "backend-failed"
                out.error = text
                return out
            answer = text
            ailib.cache_write(key, opts.backend,
                              {"success": True, "raw_response": answer,
                               "sections": {}, "error": None}, opts.cache_dir)

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
                  rules_path=str(rules.path or ""), rules_sha=rules.sha, fingerprint=key)
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
