"""The deep step of ``ccs merge --ai``: a model reads git's clean regions
for meaning, in a disposable copy, under the scope ladder.

The recipe (`aistep`) is deliberately shallow: it selects lines inside the
hunks both sides changed and never sees the rest. The case it cannot see
by construction is the maintainer's b()/c() example -- Bob changes b(),
Charlie changes c(), b() calls c(), git merges cleanly, the result is wrong
without an error. This step is the pass that reads the WHOLE file, and it
is allowed to write text -- which is exactly why its guarantee is about
SCOPE rather than content:

  * the model works in a sandbox (`aisandbox`): a worktree of the checkout
    beside a copy of the live component, with git's mechanical result
    written over the payload file. A backend with tools (the CLIs) edits
    files there; a backend without them (a server) is shown the file and
    the two diffs and answers with a diff, applied to a copy;
  * what it changed is diffed against the mechanical result and placed on
    the four-rung ladder (`airung`); within the rung the person allowed
    the candidate is KEPT as a numbered variant beside the other answers,
    and beyond it the step FAILS and reports the edits it would have made;
  * the real trees are hashed before and after (`aisandbox.Guard`); a
    backend that reached outside is `deep-escaped` and its answer is
    discarded;
  * nothing is installed, nothing is chosen: the record gains an answer,
    `chosen` does not move, and `--accept` is the gate as always. The
    loss check the recipe passes runs here as a tripwire -- recorded and
    printed, never the gate -- because a deep variant may legitimately
    contain text no side wrote.

Never cached: a run that edited files in a sandbox is not reproducible
from its inputs the way a line selection is, and a person asking twice
means to ask twice.
"""
from __future__ import annotations

import difflib
import re
import subprocess
import sys
from pathlib import Path

from . import airecord, airung, aisandbox
from .aistep import AiOptions, AiOutcome, AiStep
from .seeddecisions import norm_sha

TEMPLATE = Path(__file__).parent / "prompts" / "ai-deep.md"
DEEP_STATUSES = ("deep-proposed", "deep-empty", "deep-failed", "deep-skipped", "deep-escaped")
#: The ladder's rungs, as the prompt and the guarantees line say them.
SCOPE_PHRASES = {
    1: "the changed regions and their surrounding code",
    2: "this file only",
    3: "this file and its neighbouring files",
    4: "any file under the checkout or this component",
}
ANSWER_DIR = "answer"
_DIFF_BLOCK = re.compile(r"```diff[ \t]*\n(.*?)```", re.S)
#: How much of an earlier variant the prompt shows.
VARIANT_LINES = 400


def scope_phrase(scope: int) -> str:
    return SCOPE_PHRASES.get(scope, SCOPE_PHRASES[1])


def guarantees_for(scope: int, needed: int, *, tools: bool) -> str:
    """The line the report and the --accept question carry for a deep
    variant: what it may contain, where its edits were allowed and where
    they landed, and what did not gate it."""
    needed_word = airung.token_of(needed) if needed else "none"
    line = (f"guarantees: this variant may contain text no side wrote; the ladder allowed edits in "
            f"{scope_phrase(scope)} and every edit landed there (needed: {needed_word}); "
            f"the loss check ran as a tripwire only; your diff is the gate")
    if not tools:
        line += " -- no tools: the model saw this file and the two diffs only"
    return line


# -- the neighbours ----------------------------------------------------------------

def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def neighbours_of(label: str, *, entry, rel: str, checkout_repo: Path, live_root: Path | None) -> frozenset[str]:
    """Rung 3's territory, as sandbox-relative paths: the same component's
    files in the checkout and in the live copy, the files the payload's
    last commit touched with it, and the files that name it. The payload
    file itself is never a neighbour (its edits are rung 1 or 2). The
    manifest and git live HERE, never in `airung`."""
    co = Path(checkout_repo)
    repo_rel = f"{entry.repo}/{rel}" if rel else entry.repo
    out: set[str] = set()
    comp = co / entry.repo
    if comp.is_dir():
        for p in comp.rglob("*"):
            if p.is_file() and ".git" not in p.parts:
                out.add(f"{aisandbox.CHECKOUT_DIR}/{p.relative_to(co).as_posix()}")
    target = getattr(entry, "target", None)
    if live_root is not None and target:
        lc = Path(live_root) / target
        if lc.is_dir():
            for p in lc.rglob("*"):
                if p.is_file():
                    out.add(f"{aisandbox.LIVE_DIR}/{p.relative_to(live_root).as_posix()}")
        elif lc.is_file():
            out.add(f"{aisandbox.LIVE_DIR}/{target}")
    if (co / ".git").exists():
        r = _git(co, "log", "-1", "--name-only", "--format=", "--", repo_rel)
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                if line.strip():
                    out.add(f"{aisandbox.CHECKOUT_DIR}/{line.strip()}")
        r = _git(co, "grep", "-l", "-F", "--", Path(repo_rel).name)
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                if line.strip():
                    out.add(f"{aisandbox.CHECKOUT_DIR}/{line.strip()}")
    out.discard(f"{aisandbox.CHECKOUT_DIR}/{repo_rel}")
    return frozenset(out)


# -- the prompt --------------------------------------------------------------------

def _text(b: bytes) -> str:
    return b.decode("utf-8", "replace")


def _unified(name: str, a: bytes, b: bytes) -> str:
    diff = difflib.unified_diff(_text(a).splitlines(keepends=True), _text(b).splitlines(keepends=True),
                                fromfile=f"a/{name}", tofile=f"b/{name}")
    return "".join(diff) or "(no difference)\n"


def _fence(lang: str, body: str) -> str:
    return f"```{lang}\n{body.rstrip()}\n```"


def render_prompt(*, label: str, sb: aisandbox.Sandbox, scope: int, base: bytes, ours: bytes,
                  theirs: bytes, mechanical: bytes, dossier: str, variants: list[Path],
                  tools: bool) -> str:
    name = Path(sb.payload_rel).name
    if tools:
        live_line = (f"`{sb.live.relative_to(sb.root).as_posix()}/` is this box's live copy of the same "
                     f"component, for reference." if sb.live is not None else
                     "There is no live copy of this component beside it.")
        where = (f"You are in a disposable copy of the person's configuration. `{aisandbox.CHECKOUT_DIR}/` "
                 f"is the shared payload checkout, with the merged file at `{sb.payload_rel}`. {live_line} "
                 f"Edit in place. Nothing outside this directory is yours, and the real trees are checked "
                 f"after you finish: a change outside this directory discards your whole answer."
                 + (" You may run this file's own tests if it has any." if scope >= 2 else
                    " Do not run tests at this scope."))
        material = (f"Bob's change, from the common base:\n\n{_fence('diff', _unified(name, base, ours))}\n\n"
                    f"Charlie's change, from the common base:\n\n{_fence('diff', _unified(name, base, theirs))}")
        how = ("Read the merged file and whatever else the scope allows, decide whether the two changes "
               "still make sense together, and if not edit the file(s) in place -- the smallest edit that "
               "makes them consistent. Do not create branches, do not commit, do not touch anything the "
               "scope does not allow. Then reply with one or two sentences.")
    else:
        where = (f"You have no tools: the merged file `{name}` is shown below in full, with the two changes "
                 f"that produced it. Answer with a diff against it.")
        material = (f"Bob's change, from the common base:\n\n{_fence('diff', _unified(name, base, ours))}\n\n"
                    f"Charlie's change, from the common base:\n\n{_fence('diff', _unified(name, base, theirs))}\n\n"
                    f"The merged file, `{name}`:\n\n{_fence('', _text(mechanical))}")
        how = (f"Reply with exactly one fenced ```diff block containing a unified diff against `{name}` "
               f"(use `--- a/{name}` and `+++ b/{name}` headers and correct @@ hunk headers). If the merged "
               f"file is already correct and consistent, reply with an EMPTY diff block. Do not explain "
               f"outside the blocks.")
    shown = []
    for v in variants:
        try:
            body = v.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        cut = "\n(cut)" if len(body) > VARIANT_LINES else ""
        shown.append(f"`{v.name}`:\n\n{_fence('', chr(10).join(body[:VARIANT_LINES]) + cut)}")
    variants_text = "\n\n".join(shown) if shown else "(none)"
    template = TEMPLATE.read_text(encoding="utf-8")
    return template.format(label=label, scope_phrase=scope_phrase(scope), where=where,
                           material=material, dossier=dossier or "(nothing recorded)",
                           variants=variants_text, how=how)


# -- the no-tools answer -------------------------------------------------------------

def _apply(sb: aisandbox.Sandbox, name: str, mechanical: bytes, patch: str) -> tuple[bytes, str]:
    """Apply the model's diff to a COPY of the merged file, in the sandbox,
    with git: (the result, "") or (b"", why not)."""
    d = sb.root / ANSWER_DIR
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(mechanical)
    body = patch if patch.endswith("\n") else patch + "\n"
    (d / "answer.patch").write_text(body, encoding="utf-8", newline="\n")
    check = _git(d, "apply", "--check", "answer.patch")
    if check.returncode != 0:
        first = (check.stderr or check.stdout).strip().splitlines()
        return b"", f"the diff does not apply to the merged file: {first[0] if first else 'git apply --check failed'}"
    applied = _git(d, "apply", "answer.patch")
    if applied.returncode != 0:
        first = (applied.stderr or applied.stdout).strip().splitlines()
        return b"", f"git apply failed: {first[0] if first else 'no message'}"
    return (d / name).read_bytes(), ""


def _reason_for(edit: airung.Edit, reasons: list) -> str:
    region = (edit.region or "").strip().lower()
    for r in reasons:
        if not isinstance(r, dict):
            continue
        if str(r.get("region", "")).strip().lower() == region and region:
            return str(r.get("reason") or "")
    for r in reasons:
        if isinstance(r, dict) and edit.path.endswith(str(r.get("path", "")).strip()) and r.get("path"):
            return str(r.get("reason") or "")
    return ""


def _edit_line(e: airung.Edit) -> str:
    gone = " ".join(f"-{ln.strip()}" for ln in e.removed[:3]) or "-"
    came = " ".join(f"+{ln.strip()}" for ln in e.added[:3]) or "+"
    more = " ..." if len(e.removed) > 3 or len(e.added) > 3 else ""
    return f"{e.path} [{e.region or '-'}] rung {e.rung}: {gone} {came}{more}"


# -- the step ------------------------------------------------------------------------

def deep_step(*, label: str, base: bytes, ours: bytes, theirs: bytes, mechanical: bytes,
              variants: list[Path], entry, rel: str, checkout_repo: Path, live_root: Path | None,
              opts: AiOptions, step: AiStep, scope: int, workdir: Path, dossier: str = "",
              facts: dict | None = None, merged: Path, tripwire=None,
              base_kind: str = "inferred") -> AiOutcome:
    """Run one file through the deep step. `mechanical` is what the model
    reads for meaning (the recipe's proposal, or git's clean merge);
    `variants` are earlier answers shown last; `scope` is the rung the
    person allowed; `merged` is the person's workspace file the variant
    and the record sit beside (never read, never written); `tripwire` is
    the caller's loss check, given the variant's path, whose lines are
    recorded and never gate. `facts` are accepted for parity with the
    recipe and unused: nothing here is cached."""
    from . import ailib
    out = AiOutcome("deep-skipped", kind="deep", backend=step.backend, scope_allowed=scope)
    if not mechanical:
        out.error = "nothing to work on: no mechanical result for this file"
        return out
    try:
        backend = ailib.build_backend(opts, step.backend)
    except ValueError as e:
        out.error = str(e)
        return out
    ready = backend.probe()
    out.warning = ready.warning
    if not ready.ok:
        out.error = f"backend {step.backend!r} is not available ({ready.reason})"
        return out
    tools = "tools" in backend.capabilities
    if scope >= 3 and not tools:
        out.error = (f"{step.backend} has no tools: it can reach rung 2 (file), not {airung.token_of(scope)} "
                     f"-- pass --ai-scope hunk or file, or use a CLI backend with tools")
        return out
    out.backend_identity = backend.identity
    neighbours = neighbours_of(label, entry=entry, rel=rel, checkout_repo=checkout_repo, live_root=live_root)
    target = getattr(entry, "target", None)
    live_component = (Path(live_root) / target) if (live_root is not None and target) else None
    guard = aisandbox.Guard.take([checkout_repo, live_component])
    sb = aisandbox.prepare(workdir=workdir, checkout_repo=checkout_repo, live_root=live_root,
                           entry=entry, rel=rel, mechanical=mechanical)
    try:
        before = aisandbox.digest(sb.root)
        prompt = render_prompt(label=label, sb=sb, scope=scope, base=base, ours=ours, theirs=theirs,
                               mechanical=mechanical, dossier=dossier, variants=list(variants), tools=tools)
        req = ailib.Request(prompt=prompt, schema=None, timeout=opts.timeout,
                            workdir=str(sb.root) if tools else "",
                            stream_to=sys.stdout if opts.verbose else None)
        resp = backend.invoke(req)                 # never through the cache
        out.model_used, out.honoured = resp.model_used, resp.honoured
        if not resp.ok:
            out.status = "deep-failed"
            out.error = resp.error
            return out
        data = ailib.parsers.json_block(resp.text)
        data = data if isinstance(data, dict) else {}
        out.summary = str(data.get("summary") or "")
        reasons = data.get("edits") if isinstance(data.get("edits"), list) else []
        if tools:
            after = aisandbox.digest(sb.root)
            touched = aisandbox.changed(before, after)
            candidate = sb.payload_file.read_bytes() if sb.payload_file.is_file() else b""
            others: dict[str, tuple[bytes, bytes]] = {}
            for p in touched:
                if p == sb.payload_rel:
                    continue
                f = sb.root / Path(p)
                others[p] = (aisandbox.before_content(sb, p, live_root), f.read_bytes() if f.is_file() else b"")
        else:
            blocks = _DIFF_BLOCK.findall(resp.text)
            if not blocks:
                out.status = "deep-failed"
                out.error = f"{step.backend} answered without a ```diff block -- nothing to apply"
                return out
            patch = blocks[-1]
            if not patch.strip():
                candidate, touched, others = mechanical, [], {}
            else:
                candidate, why = _apply(sb, Path(sb.payload_rel).name, mechanical, patch)
                if why:
                    out.status = "deep-failed"
                    out.error = why
                    return out
                touched, others = [sb.payload_rel], {}
        out.escapes = guard.escapes()
        if out.escapes:
            out.status = "deep-escaped"
            out.error = (f"{step.backend} changed {len(out.escapes)} real file(s) outside the sandbox -- "
                         f"its answer is discarded")
            return out
        verdict = airung.needed_rung(label=label, base=base, mechanical=mechanical, candidate=candidate,
                                     others=others, neighbours=neighbours)
        out.scope_needed = verdict.needed
        out.touched = list(touched)
        out.edits = [(e.path, e.region, e.rung, _reason_for(e, reasons)) for e in verdict.edits]
        out.reports = [_edit_line(e) for e in verdict.edits]
        out.guarantees = guarantees_for(scope, verdict.needed, tools=tools)
        if verdict.needed == 0:
            out.status = "deep-empty"
            return out
        if verdict.needed > scope:
            out.status = "deep-failed"
            out.error = (f"the model's edits needed {airung.token_of(verdict.needed)} scope and "
                         f"{airung.token_of(scope)} was allowed -- nothing kept; the edits it would have "
                         f"made are listed")
            return out
        rec_path = airecord.record_path(merged)
        rec = airecord.load(rec_path)
        if rec is None:
            # The recipe had nothing to do (git merged the file clean), so no
            # record exists: create one around git's own result, so the deep
            # answer is a variant OF something and the numbering holds.
            rec = airecord.new_record(proposal=mechanical, ours=ours, theirs=theirs, base=base,
                                      base_kind=base_kind, backend="git", rules_path="", rules_sha="",
                                      fingerprint="", valid=True, failures=[], kind=airecord.MECHANICAL,
                                      identity="git merge-file --diff3")
        n = airecord.add_answer(rec, kind=airecord.DEEP, backend=step.backend, identity=backend.identity,
                                model_used=resp.model_used, honoured=list(resp.honoured), fingerprint="",
                                proposal_sha=norm_sha(candidate),
                                scope={"allowed": scope, "needed": verdict.needed},
                                touched=list(touched), variant_of=rec.chosen, guarantees=out.guarantees,
                                summary=out.summary, status="deep-proposed")
        variant = airecord.proposal_path(merged, n)
        variant.parent.mkdir(parents=True, exist_ok=True)
        variant.write_bytes(candidate)
        airecord.write(rec_path, rec)
        out.variant = variant
        out.record = rec
        out.status = "deep-proposed"
        if tripwire is not None:
            try:
                out.tripwire = [str(x) for x in tripwire(variant)]
            except Exception as e:                                       # noqa: BLE001
                out.tripwire = [f"the loss check itself failed: {e}"]
        return out
    finally:
        aisandbox.release(sb)
