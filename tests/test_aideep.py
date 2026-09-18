"""U4 of the deep merge (#64): the deep step -- a model reads git's clean
regions for meaning, in a disposable copy, under the scope ladder.

The eight things the design promises (its acceptance checks C1-C8; C6 and
C7 are the plan's, U5):

  C1  the b()/c() case is fixed at rung 1 by a backend with tools
  C2  a control with nothing wrong yields an empty change
  C3  every edit is reported with the region, the rung and the model's reason
  C4  the real trees are never touched: the checkout and the live component
      hash the same after the run, and a backend that escapes the sandbox is
      reported as such with no variant kept
  C5  a scope the backend cannot reach is refused before any call; an edit
      beyond the allowed rung fails, with the edits as the report
  C8  the loss check runs as a tripwire: recorded and printed, never the gate

Written BEFORE the modules (red by construction). Two fake transports:
a `cli` that writes into `req.workdir` exactly what the test scripts (the
tools form), and an `openai_compat` that answers with a unified diff (the
no-tools form). Nothing here touches a real model.
"""
from __future__ import annotations

import hashlib
import json
import subprocess as sp
from pathlib import Path

import pytest

from bc_fixture import BASE, FIXED_BROKEN, FIXED_IN_A, MERGED_BROKEN, OURS, THEIRS_BROKEN

from conftest import GIT_ID

HAND_DIFF = ("--- a/merged.py\n+++ b/merged.py\n@@ -5,4 +5,4 @@\n def b(x):\n     v = c(x)\n"
             "-    return v * 2\n+    return (v[0] * 2, v[1] * 2)\n \n")      # the last line: a blank context line

ANSWER_JSON = json.dumps({"summary": "b() now adapts to the tuple c() returns",
                          "edits": [{"path": "merged.py", "region": "b",
                                     "reason": "c() returns a pair now; doubling a tuple repeats it"}]})


# -- the no-tools apply, against the shapes a real model wrote (v0.6.8, U8) ------------------
#
# qwen3.8-27b's answers on 2026-09-16, verbatim: a context hunk whose header
# count is off by one, and a zero-context hunk. Both are right answers; both
# were refused by `git apply` as the step called it. The third test is the
# guard the other way: the flags that take those must not take a hunk whose
# removed line is not in the file.

FIXED_UNPACKED = MERGED_BROKEN.replace("    v = c(x)\n    return v * 2\n",
                                       "    v1, v2 = c(x)\n    return (v1 * 2, v2 * 2)\n")
MISCOUNTED_DIFF = "\n".join([
    "--- a/s.py", "+++ b/s.py", "@@ -5,7 +5,8 @@", " ", " def b(x):", "-    v = c(x)", "-    return v * 2",
    "+    v1, v2 = c(x)", "+    return (v1 * 2, v2 * 2)", " ", " ", " def a(x):", ""])
ZERO_CONTEXT_DIFF = "\n".join([
    "--- a/s.py", "+++ b/s.py", "@@ -7,1 +7,1 @@", "-    return v * 2", "+    return (v[0] * 2, v[1] * 2)", ""])
WRONG_LINE_DIFF = "\n".join([
    "--- a/s.py", "+++ b/s.py", "@@ -7,1 +7,1 @@", "-    return v * 3", "+    return (v[0] * 2, v[1] * 2)", ""])


class _Root:
    """The one thing `_apply` reads from a sandbox."""
    def __init__(self, root: Path) -> None:
        self.root = root


def test_apply_takes_a_hunk_whose_count_is_off_by_one_v068(tmp_path):
    from dazzle_claude_config import aideep
    assert FIXED_UNPACKED != MERGED_BROKEN
    got, why = aideep._apply(_Root(tmp_path), "s.py", MERGED_BROKEN.encode(), MISCOUNTED_DIFF)
    assert why == "", why
    assert got.decode().replace("\r\n", "\n") == FIXED_UNPACKED


def test_apply_takes_a_zero_context_hunk_v068(tmp_path):
    from dazzle_claude_config import aideep
    got, why = aideep._apply(_Root(tmp_path), "s.py", MERGED_BROKEN.encode(), ZERO_CONTEXT_DIFF)
    assert why == "", why
    assert got.decode().replace("\r\n", "\n") == FIXED_BROKEN


def test_apply_still_refuses_a_hunk_whose_removed_line_is_not_in_the_file_v068(tmp_path):
    """--recount and --unidiff-zero relax the counts and the context, never
    the removed lines: a hunk that deletes a line the file does not have is
    still refused, with git's sentence."""
    from dazzle_claude_config import aideep
    got, why = aideep._apply(_Root(tmp_path), "s.py", MERGED_BROKEN.encode(), WRONG_LINE_DIFF)
    assert got == b"" and "does not apply" in why, why


# -- which diff block is the answer (v0.6.9, finding 10) ---------------------------------------
#
# Part B's `bc-python-fix-in-a@file` line (2026-09-16): the model wrote a
# bare snippet, then the real patch, then another snippet. The capture took
# the LAST block, which has no hunk, and 0.6.8's rule read it as "nothing to
# change" -- a fix reported as no change, which is worse than a refusal.
# The block WITH the hunk is the answer; when no block has one, the model's
# own json decides: no edits declared is no change, edits declared with
# nothing applicable is a refusal that says so.

SNIPPET_BLOCK = "```diff\n def b(x):\n-    v = c(x)\n-    return v * 2\n+    return tuple(vi * 2 for vi in c(x))\n```\n"
REAL_PATCH_BLOCK = ("```diff\n--- a/merged.py\n+++ b/merged.py\n@@ -5,4 +5,4 @@\n def b(x):\n     v = c(x)\n"
                    "-    return v * 2\n+    return (v[0] * 2, v[1] * 2)\n \n```\n")
EDITS_JSON = "```json\n" + ANSWER_JSON + "\n```\n"
NO_EDITS_JSON = "```json\n" + json.dumps({"summary": "nothing needed changing", "edits": []}) + "\n```\n"


def test_the_block_with_the_hunk_is_the_answer_not_the_last_block_v069(tmp_path, fakes):
    from dazzle_claude_config import airecord
    w = _world(tmp_path)
    _NoTools.reply = "A snippet first:\n\n" + SNIPPET_BLOCK + "\nThe patch:\n\n" + REAL_PATCH_BLOCK + "\nOr:\n\n" + SNIPPET_BLOCK + "\n" + EDITS_JSON
    out = _deep(w, backend="lmstudio", scope=1)
    assert out.status == "deep-proposed", out.error
    assert airecord.proposal_path(w["merged"], 1).read_text(encoding="utf-8").replace("\r\n", "\n") == FIXED_BROKEN


def test_snippets_only_with_edits_declared_is_a_refusal_that_names_the_missing_hunk_v069(tmp_path, fakes):
    from dazzle_claude_config import airecord
    w = _world(tmp_path)
    _NoTools.reply = "Change b like so:\n\n" + SNIPPET_BLOCK + "\n" + EDITS_JSON
    out = _deep(w, backend="lmstudio", scope=1)
    assert out.status == "deep-failed", out.status
    assert "no hunk" in out.error and "b" in out.error, out.error
    assert not airecord.proposal_path(w["merged"], 1).exists()
    assert out.reply is not None and out.reply.is_file()


def test_the_last_hunked_block_wins_over_an_earlier_false_start_v069_M2(tmp_path, fakes):
    """M2 of the 0.6.9 sweep: a model may write a false-start hunk and then
    its real patch. The LAST block with a hunk is the answer; the first one
    here removes a line the file does not have and would be refused."""
    from dazzle_claude_config import airecord
    w = _world(tmp_path)
    false_start = "```diff\n" + WRONG_LINE_DIFF.replace("a/s.py", "a/merged.py").replace("b/s.py", "b/merged.py") + "```\n"
    _NoTools.reply = "First attempt:\n\n" + false_start + "\nCorrected:\n\n" + REAL_PATCH_BLOCK + "\n" + EDITS_JSON
    out = _deep(w, backend="lmstudio", scope=1)
    assert out.status == "deep-proposed", out.error
    assert airecord.proposal_path(w["merged"], 1).read_text(encoding="utf-8").replace("\r\n", "\n") == FIXED_BROKEN


def test_a_hunk_is_an_anchored_hunk_line_not_a_bare_at_at_anywhere_v069_M3(tmp_path, fakes):
    """M3 of the 0.6.9 sweep: a snippet that merely mentions `@@` mid-line
    is not a hunk. With no edits declared it is no change; a loose
    detector would hand the snippet to git and refuse it."""
    from dazzle_claude_config import airecord
    w = _world(tmp_path)
    chatter = "```diff\n def b(x):\n-    return v * 2   (see the @@ header in a real patch)\n+    return (v[0] * 2, v[1] * 2)\n```\n"
    _NoTools.reply = "For reference only:\n\n" + chatter + "\n" + NO_EDITS_JSON
    out = _deep(w, backend="lmstudio", scope=1)
    assert out.status == "deep-empty", (out.status, out.error)
    assert not airecord.proposal_path(w["merged"], 1).exists()


def test_snippets_only_with_no_edits_declared_is_no_change_v069(tmp_path, fakes):
    from dazzle_claude_config import airecord
    w = _world(tmp_path)
    _NoTools.reply = "The changes compose. For reference:\n\n" + SNIPPET_BLOCK + "\n" + NO_EDITS_JSON
    out = _deep(w, backend="lmstudio", scope=1)
    assert out.status == "deep-empty", (out.status, out.error)
    assert not airecord.proposal_path(w["merged"], 1).exists()


def test_a_backend_failure_keeps_no_reply_and_the_outcome_names_none_v068_M6(tmp_path, fakes):
    """M6 of the 0.6.8 sweep: the reply is kept only after the backend
    answered. A failure -- a timeout, an unreachable server -- has no text
    to keep, and an empty reply file the report then pointed at would
    mislead. Killed by asserting both the file and the outcome's pointer
    are absent."""
    from dazzle_claude_config import airecord
    w = _world(tmp_path)
    _NoTools.fail = ("no answer from fake-27b within 120s -- if it is generating slowly, the usual cause "
                     "is a context window far larger than the prompt, not the model itself")
    out = _deep(w, backend="lmstudio", scope=1)
    assert out.status == "deep-failed" and "within 120s" in out.error and _NoTools.calls == 1
    assert out.reply is None
    assert not airecord.reply_path(w["merged"]).exists()
    assert not airecord.reply_path(w["merged"], 1).exists()


# -- a world: a git checkout and a live component -----------------------------------

def _git(cwd: Path, *args: str) -> str:
    r = sp.run(["git", *GIT_ID, "-C", str(cwd), *args], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, f"git {args}: {r.stderr}"
    return r.stdout


def _world(tmp_path: Path) -> dict:
    """The checkout holds the payload's copy (theirs) at HEAD, a neighbour
    in the same component, a file whose last commit touched the payload
    file with it, a file that names it, and a far file. The live root holds
    the person's copy (ours) and the neighbour."""
    from dazzle_claude_config.manifest import Entry
    co, live, user = tmp_path / "co", tmp_path / "live", tmp_path / "user"
    (co / "dotclaude" / "skills").mkdir(parents=True)
    (co / "dotclaude" / "agents").mkdir(parents=True)
    (live / "skills").mkdir(parents=True)
    user.mkdir()
    sp.run(["git", "init", "-q", "-b", "main", str(co)], check=True)
    (co / "dotclaude" / "skills" / "merged.py").write_text(BASE, encoding="utf-8")
    (co / "dotclaude" / "skills" / "helper.md").write_text("helper: unrelated notes\n", encoding="utf-8")
    (co / "dotclaude" / "agents" / "caller.md").write_text("see skills/merged.py for the maths\n", encoding="utf-8")
    (co / "README.md").write_text("a far file\n", encoding="utf-8")
    _git(co, "add", "-A")
    _git(co, "commit", "-qm", "base")
    (co / "dotclaude" / "skills" / "merged.py").write_text(THEIRS_BROKEN, encoding="utf-8")
    (co / "dotclaude" / "skills" / "sibling.md").write_text("changed in the same commit\n", encoding="utf-8")
    _git(co, "add", "-A")
    _git(co, "commit", "-qm", "theirs")
    (live / "skills" / "merged.py").write_text(OURS, encoding="utf-8")
    (live / "skills" / "helper.md").write_text("helper: unrelated notes\n", encoding="utf-8")
    entry = Entry(repo="dotclaude/skills", strategy="copy", territory="dotclaude", target="skills")
    ws = user / "merge" / "ccs"
    ws.mkdir(parents=True)
    return dict(co=co, live=live, user=user, ws=ws, entry=entry, rel="merged.py",
                merged=ws / "skills__merged.py.merged", label="skills/merged.py")


def _digest(root: Path) -> dict[str, str]:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and ".git" not in p.parts:
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# -- the fake transports -------------------------------------------------------------

class _Tools:
    """A fake `cli` transport with tools: it writes what the test scripts
    into the request's workdir (paths relative to it), then answers with
    the json block. `escape` names an ABSOLUTE path to write outside."""
    script: list[tuple[str, str]] = []
    escape: Path | None = None
    calls: int = 0
    seen: dict = {}

    def probe(self, spec):
        from dazzle_claude_config._vendor.ailib.types import Readiness
        return Readiness(True, "its CLI was found: C:/fake/claude.exe", warning="")

    def capabilities(self, spec):
        return frozenset({"model", "stream", "tools"})

    def invoke(self, spec, req):
        from dazzle_claude_config._vendor.ailib.types import Response
        _Tools.calls += 1
        _Tools.seen = {"workdir": req.workdir, "prompt": req.prompt}
        assert req.workdir, "the tools form must run in the sandbox"
        root = Path(req.workdir)
        for rel, text in _Tools.script:
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        if _Tools.escape is not None:
            _Tools.escape.write_text("the model reached outside\n", encoding="utf-8")
        return Response("answered", text="Done.\n```json\n" + ANSWER_JSON + "\n```\n",
                        model_used="fake-opus", honoured=("model", "tools"))


class _NoTools:
    """A fake `openai_compat` transport: no tools, answers with a diff."""
    diff: str = HAND_DIFF
    calls: int = 0
    fail: str = ""                 # when set, the backend fails with this sentence instead of answering
    reply: str = ""                # when set, the whole reply verbatim (several blocks, prose, anything)
    interrupt: bool = False        # when set, the call raises KeyboardInterrupt (the person's Ctrl-C)

    def probe(self, spec):
        from dazzle_claude_config._vendor.ailib.types import Readiness
        return Readiness(True, "http://fake/v1 -- reachable, model fake-27b", warning="")

    def capabilities(self, spec):
        return frozenset({"model", "schema"})

    def invoke(self, spec, req):
        from dazzle_claude_config._vendor.ailib.types import Response
        _NoTools.calls += 1
        assert not req.workdir, "the no-tools form never names a workdir"
        if _NoTools.interrupt:
            raise KeyboardInterrupt
        if _NoTools.fail:
            return Response("failed", error=_NoTools.fail)
        if _NoTools.reply:
            return Response("answered", text=_NoTools.reply, model_used="fake-27b", honoured=("model",))
        return Response("answered", text="```diff\n" + _NoTools.diff + "```\n\n```json\n" + ANSWER_JSON + "\n```\n",
                        model_used="fake-27b", honoured=("model",))


@pytest.fixture
def fakes(monkeypatch):
    from dazzle_claude_config._vendor.ailib import backend as _bm
    _bm.transport_for("cli")
    monkeypatch.setitem(_bm._TRANSPORTS, "cli", _Tools())
    monkeypatch.setitem(_bm._TRANSPORTS, "openai_compat", _NoTools())
    _Tools.script, _Tools.escape, _Tools.calls, _Tools.seen = [], None, 0, {}
    _NoTools.diff, _NoTools.calls, _NoTools.fail, _NoTools.reply = HAND_DIFF, 0, "", ""
    _NoTools.interrupt = False


def _opts(w, backend="claude"):
    from dazzle_claude_config import aistep
    return aistep.AiOptions(rules_dir=w["user"] / "rules", prompts_dir=w["user"] / "prompts",
                            cache_dir=w["user"] / "cache", backend=backend, timeout=20)


def _deep(w, *, backend="claude", scope=1, tripwire=None, mechanical=MERGED_BROKEN):
    from dazzle_claude_config import aideep, aistep
    return aideep.deep_step(
        label=w["label"], base=BASE.encode(), ours=OURS.encode(), theirs=THEIRS_BROKEN.encode(),
        mechanical=mechanical.encode(), variants=[], entry=w["entry"], rel=w["rel"],
        checkout_repo=w["co"], live_root=w["live"], opts=_opts(w, backend),
        step=aistep.AiStep("deep", backend), scope=scope, workdir=w["ws"] / "skills__merged.py.ai-deep",
        dossier="(no dossier)", facts={}, merged=w["merged"], tripwire=tripwire)


# -- C1: the b()/c() case, with tools --------------------------------------------------

def test_c1_the_bc_case_is_fixed_at_rung_1_and_kept_as_a_variant(tmp_path, fakes):
    from dazzle_claude_config import airecord
    w = _world(tmp_path)
    _Tools.script = [("checkout/dotclaude/skills/merged.py", FIXED_BROKEN)]
    out = _deep(w, scope=1)
    assert out.status == "deep-proposed", out.error
    assert out.kind == "deep" and out.scope_allowed == 1 and out.scope_needed == 1
    assert out.variant == airecord.proposal_path(w["merged"], 1)
    assert out.variant.read_text(encoding="utf-8") == FIXED_BROKEN
    assert _Tools.calls == 1 and Path(_Tools.seen["workdir"]).name == "skills__merged.py.ai-deep"
    assert "the ladder allowed edits in" in out.guarantees and "needed: hunk" in out.guarantees
    rec = airecord.load(airecord.record_path(w["merged"]))
    assert rec is not None and len(rec.answers) == 2 and rec.chosen == 0      # chosen never moved
    assert airecord.answer_kind(rec.answers[0]) == "mechanical" and rec.answers[0]["backend"] == "git"
    assert airecord.answer_kind(rec.answers[1]) == "deep"
    assert rec.answers[1]["scope"] == {"allowed": 1, "needed": 1}
    assert rec.answers[1]["variant_of"] == 0 and rec.answers[1]["status"] == "deep-proposed"
    assert not airecord.proposal_path(w["merged"]).exists()                    # no bare .merged-ai


def test_the_sandbox_is_released_and_the_workdir_holds_no_worktree_afterwards(tmp_path, fakes):
    w = _world(tmp_path)
    _Tools.script = [("checkout/dotclaude/skills/merged.py", FIXED_BROKEN)]
    _deep(w, scope=1)
    assert not (w["ws"] / "skills__merged.py.ai-deep" / "checkout").exists()
    assert "ai-deep" not in _git(w["co"], "worktree", "list")


# -- run while alive (v0.6.10, 2026-09-18): what a failure leaves behind ------------------

def test_a_call_declared_dead_keeps_the_sandbox_and_names_what_the_model_was_doing_v0610(tmp_path, fakes, monkeypatch):
    """The deep step on Opus was cut mid-thought on a real file and left
    nothing to read. Now a failed call keeps the sandbox (named), and when
    the backend went silent the report names Claude Code's own transcript
    of the run, found under the config directory by the sandbox's cwd."""
    import re
    w = _world(tmp_path)
    _NoTools.fail = "fake-27b gave no sign of life for 3s -- stopped"
    cfg = tmp_path / "claude-config"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    root = w["ws"] / "skills__merged.py.ai-deep"
    tdir = cfg / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(root))
    tdir.mkdir(parents=True)
    (tdir / "abc123.jsonl").write_text('{"type":"user"}\n', encoding="utf-8")
    out = _deep(w, backend="lmstudio", scope=1)
    assert out.status == "deep-failed" and "no sign of life" in out.error
    assert any("sandbox kept" in line and str(root) in line for line in out.reports), out.reports
    assert any("what it was doing" in line and "abc123.jsonl" in line for line in out.reports), out.reports
    assert (root / "checkout").exists()


def test_a_call_that_fails_for_another_reason_keeps_the_sandbox_but_names_no_transcript_v0610(tmp_path, fakes, monkeypatch):
    w = _world(tmp_path)
    _NoTools.fail = "fake-27b exited with code 3: boom"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "empty-config"))
    out = _deep(w, backend="lmstudio", scope=1)
    assert out.status == "deep-failed"
    assert any("sandbox kept" in line for line in out.reports)
    assert not any("what it was doing" in line for line in out.reports)


def test_the_persons_ctrl_c_keeps_the_sandbox_too_v0610(tmp_path, fakes):
    w = _world(tmp_path)
    _NoTools.interrupt = True
    root = w["ws"] / "skills__merged.py.ai-deep"
    with pytest.raises(KeyboardInterrupt):
        _deep(w, backend="lmstudio", scope=1)
    assert (root / "checkout").exists()


# -- C2: the control -------------------------------------------------------------------

def test_c2_a_model_that_changes_nothing_is_deep_empty_with_no_variant(tmp_path, fakes):
    from dazzle_claude_config import airecord
    w = _world(tmp_path)
    _Tools.script = []                                                       # reads, writes nothing
    out = _deep(w, scope=1)
    assert out.status == "deep-empty" and out.variant is None and out.scope_needed == 0
    assert not airecord.proposal_path(w["merged"], 1).exists()


def test_c2_the_no_tools_form_with_an_empty_diff_is_deep_empty(tmp_path, fakes):
    w = _world(tmp_path)
    _NoTools.diff = ""
    out = _deep(w, backend="lmstudio", scope=1)
    assert out.status == "deep-empty" and _NoTools.calls == 1


# -- C3: the edits, with reasons -------------------------------------------------------

def test_c3_every_edit_is_reported_with_region_rung_and_the_models_reason(tmp_path, fakes):
    w = _world(tmp_path)
    _Tools.script = [("checkout/dotclaude/skills/merged.py", FIXED_BROKEN)]
    out = _deep(w, scope=1)
    assert out.edits == [("skills/merged.py", "b", 1, "c() returns a pair now; doubling a tuple repeats it")]
    assert out.summary == "b() now adapts to the tuple c() returns"
    assert out.touched == ["checkout/dotclaude/skills/merged.py"]


# -- C4: the real trees --------------------------------------------------------------

def test_c4_the_real_checkout_and_live_component_are_hash_identical_after_a_run(tmp_path, fakes):
    w = _world(tmp_path)
    before = (_digest(w["co"]), _digest(w["live"]), _git(w["co"], "status", "--porcelain"))
    _Tools.script = [("checkout/dotclaude/skills/merged.py", FIXED_BROKEN),
                     ("checkout/dotclaude/skills/helper.md", "the model edited a neighbour too\n")]
    out = _deep(w, scope=3)
    assert out.status == "deep-proposed" and out.scope_needed == 3
    assert out.escapes == []
    assert (_digest(w["co"]), _digest(w["live"]), _git(w["co"], "status", "--porcelain")) == before


def test_c4_a_backend_that_escapes_the_sandbox_is_reported_and_keeps_no_variant(tmp_path, fakes):
    from dazzle_claude_config import airecord
    w = _world(tmp_path)
    real = w["live"] / "skills" / "helper.md"
    _Tools.script = [("checkout/dotclaude/skills/merged.py", FIXED_BROKEN)]
    _Tools.escape = real                                                    # writes OUTSIDE the sandbox
    out = _deep(w, scope=1)
    assert out.status == "deep-escaped"
    assert any("helper.md" in e for e in out.escapes)
    assert out.variant is None and not airecord.proposal_path(w["merged"], 1).exists()
    real.write_text("helper: unrelated notes\n", encoding="utf-8")         # the test's own repair


# -- C5: the scope --------------------------------------------------------------------

def test_c5_a_scope_that_needs_tools_is_refused_before_any_call_on_a_no_tools_backend(tmp_path, fakes):
    w = _world(tmp_path)
    out = _deep(w, backend="lmstudio", scope=3)
    assert out.status == "deep-skipped" and _NoTools.calls == 0
    assert "no tools" in out.error and "rung 2 (file)" in out.error and "neighbours" in out.error


def test_c5_an_edit_beyond_the_allowed_rung_fails_with_the_edits_as_the_report(tmp_path, fakes):
    from dazzle_claude_config import airecord
    w = _world(tmp_path)
    _Tools.script = [("checkout/dotclaude/skills/merged.py", FIXED_IN_A)]      # a() -- rung 2
    out = _deep(w, scope=1)
    assert out.status == "deep-failed" and out.scope_needed == 2 and out.scope_allowed == 1
    assert out.variant is None and not airecord.proposal_path(w["merged"], 1).exists()
    assert [(e[1], e[2]) for e in out.edits] == [("a", 2)]
    assert "needed file" in out.error and "hunk" in out.error
    assert any("def a(x)" in line or "return t[0]" in line for line in out.reports)


def test_c5_the_same_edit_within_a_wider_scope_is_kept(tmp_path, fakes):
    w = _world(tmp_path)
    _Tools.script = [("checkout/dotclaude/skills/merged.py", FIXED_IN_A)]
    out = _deep(w, scope=2)
    assert out.status == "deep-proposed" and out.scope_needed == 2
    assert "needed: file" in out.guarantees


def test_a_far_file_is_rung_4_and_a_neighbour_is_rung_3(tmp_path, fakes):
    w = _world(tmp_path)
    _Tools.script = [("checkout/README.md", "a far file, edited\n")]
    out = _deep(w, scope=3)
    assert out.status == "deep-failed" and out.scope_needed == 4
    _Tools.script = [("live/skills/helper.md", "the live neighbour, edited\n")]
    out = _deep(w, scope=3)
    assert out.status == "deep-proposed" and out.scope_needed == 3


# -- the neighbours ----------------------------------------------------------------------

def test_neighbours_are_the_component_the_commit_and_the_files_that_name_it(tmp_path, fakes):
    from dazzle_claude_config import aideep
    w = _world(tmp_path)
    n = aideep.neighbours_of(w["label"], entry=w["entry"], rel=w["rel"], checkout_repo=w["co"], live_root=w["live"])
    assert "checkout/dotclaude/skills/helper.md" in n            # the same component
    assert "live/skills/helper.md" in n                          # the live component's copy
    assert "checkout/dotclaude/skills/sibling.md" in n           # touched by the payload's last commit
    assert "checkout/dotclaude/agents/caller.md" in n            # names the file
    assert "checkout/README.md" not in n                         # far
    assert "checkout/dotclaude/skills/merged.py" not in n        # the payload file is rung 1/2, not 3


# -- the no-tools form ---------------------------------------------------------------------

def test_the_no_tools_form_applies_the_diff_and_keeps_the_variant(tmp_path, fakes):
    from dazzle_claude_config import airecord
    w = _world(tmp_path)
    out = _deep(w, backend="lmstudio", scope=1)
    assert out.status == "deep-proposed", out.error
    assert out.variant.read_text(encoding="utf-8") == FIXED_BROKEN
    assert "no tools" in out.guarantees
    rec = airecord.load(airecord.record_path(w["merged"]))
    assert rec.answers[1]["backend"] == "lmstudio" and rec.chosen == 0


def test_a_diff_that_does_not_apply_is_deep_failed_with_gits_sentence(tmp_path, fakes):
    w = _world(tmp_path)
    _NoTools.diff = HAND_DIFF.replace("-    return v * 2", "-    return something else")
    out = _deep(w, backend="lmstudio", scope=1)
    assert out.status == "deep-failed" and out.variant is None
    assert "apply" in out.error


def test_a_reply_without_a_diff_block_is_deep_failed(tmp_path, fakes, monkeypatch):
    from dazzle_claude_config._vendor.ailib.types import Response
    w = _world(tmp_path)
    monkeypatch.setattr(_NoTools, "invoke", lambda self, spec, req: Response("answered", text="I think it is fine."))
    out = _deep(w, backend="lmstudio", scope=1)
    assert out.status == "deep-failed" and "diff" in out.error


# -- C8: the loss check is a tripwire ----------------------------------------------------

def test_c8_the_loss_check_is_recorded_and_never_the_gate(tmp_path, fakes):
    w = _world(tmp_path)
    _Tools.script = [("checkout/dotclaude/skills/merged.py", FIXED_BROKEN)]
    seen = {}

    def tripwire(candidate: Path) -> list[str]:
        seen["path"] = candidate
        return ["lost 1 line that your live file has: return v * 2"]

    out = _deep(w, scope=1, tripwire=tripwire)
    assert out.status == "deep-proposed"                                     # never the gate
    assert out.tripwire == ["lost 1 line that your live file has: return v * 2"]
    assert seen["path"] == out.variant
    assert "tripwire" in out.guarantees


def test_the_deep_prompt_template_is_declared_package_data_and_ships():
    """The recipe's template earned this test the hard way (a file that
    exists in a checkout and is missing after `pip install`); the deep
    step's template gets the same guard from day one."""
    import importlib.resources
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert '"prompts/ai-deep.md"' in pyproject, "prompts/ai-deep.md is not package-data in pyproject.toml"
    packaged = importlib.resources.files("dazzle_claude_config").joinpath("prompts/ai-deep.md")
    assert packaged.is_file()
    from dazzle_claude_config import aideep
    text = aideep.TEMPLATE.read_text(encoding="utf-8")
    for placeholder in ("{label}", "{scope_phrase}", "{where}", "{material}", "{dossier}", "{variants}", "{how}"):
        assert placeholder in text, placeholder


# -- v0.6.4 mutation sweep (survivor kills) ------------------------------------------------

def test_a_nested_git_directory_inside_a_component_is_never_a_neighbour_M2(tmp_path, fakes):
    """v0.6.4 sweep, survivor M2: a skill cloned as its own repository sits
    inside a component; its `.git/` internals are not configuration (the
    manifest's default exclude says the same) and must not be rung-3
    territory, while the files beside them are."""
    from dazzle_claude_config import aideep
    w = _world(tmp_path)
    nested = w["co"] / "dotclaude" / "skills" / "vendored"
    (nested / ".git").mkdir(parents=True)
    (nested / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (nested / "README.md").write_text("a vendored skill\n", encoding="utf-8")
    n = aideep.neighbours_of(w["label"], entry=w["entry"], rel=w["rel"], checkout_repo=w["co"], live_root=w["live"])
    assert "checkout/dotclaude/skills/vendored/README.md" in n
    assert not any("/.git/" in p for p in n)


def test_a_neighbour_edit_reports_what_went_and_what_came_in_that_order_M11(tmp_path, fakes):
    """v0.6.4 sweep, survivor M11: the before and after contents of a
    neighbour edit were swappable without a test noticing."""
    w = _world(tmp_path)
    _Tools.script = [("live/skills/helper.md", "the live neighbour, edited\n")]
    out = _deep(w, scope=3)
    assert out.status == "deep-proposed" and out.scope_needed == 3
    line = next(r for r in out.reports if "live/skills/helper.md" in r)
    assert "-helper: unrelated notes" in line and "+the live neighbour, edited" in line
    assert line.index("-helper") < line.index("+the live")


def test_an_edit_to_gitignore_is_seen_and_the_worktree_pointer_is_not_M14(tmp_path, fakes):
    """v0.6.4 sweep, survivor M14: the digest skips exactly the `.git`
    entries (a worktree's pointer file, a repository's directory) and
    nothing else -- a `.gitignore` the model touches is a real edit, at
    rung 4."""
    w = _world(tmp_path)
    _Tools.script = [("checkout/.gitignore", "*.tmp\n")]
    out = _deep(w, scope=1)
    assert out.status == "deep-failed" and out.scope_needed == 4
    assert "checkout/.gitignore" in out.touched
    assert not any(p.endswith("/.git") or p == "checkout/.git" for p in out.touched)


def test_a_file_the_model_creates_is_a_touched_file_M15(tmp_path, fakes):
    """v0.6.4 sweep, survivor M15: an ADDED file has no before-hash, and a
    digest comparison over the intersection of the two would miss it."""
    w = _world(tmp_path)
    _Tools.script = [("checkout/dotclaude/skills/merged.py", FIXED_BROKEN),
                     ("checkout/dotclaude/skills/new-note.md", "the model wrote a new file\n")]
    out = _deep(w, scope=4)
    assert out.status == "deep-proposed" and out.scope_needed == 4
    assert "checkout/dotclaude/skills/new-note.md" in out.touched
    added = next(e for e in out.edits if e[0] == "checkout/dotclaude/skills/new-note.md")
    assert added[2] == 4


def test_a_checkout_that_is_not_a_repository_is_copied_and_before_content_is_the_originals_M17(tmp_path, fakes):
    """v0.6.4 sweep, survivor M17: without a repository the sandbox holds
    a plain copy, and a neighbour's BEFORE content must come from the real
    tree, not from the copy the model has already edited."""
    from dazzle_claude_config import aideep, aistep
    w = _world(tmp_path)
    plain = tmp_path / "plain"
    import shutil
    shutil.copytree(w["co"], plain, ignore=shutil.ignore_patterns(".git"))
    _Tools.script = [("checkout/dotclaude/skills/helper.md", "the checkout neighbour, edited\n")]
    out = aideep.deep_step(
        label=w["label"], base=BASE.encode(), ours=OURS.encode(), theirs=THEIRS_BROKEN.encode(),
        mechanical=MERGED_BROKEN.encode(), variants=[], entry=w["entry"], rel=w["rel"],
        checkout_repo=plain, live_root=w["live"], opts=_opts(w), step=aistep.AiStep("deep", "claude"),
        scope=3, workdir=w["ws"] / "skills__merged.py.ai-deep", dossier="", facts={},
        merged=w["merged"], tripwire=None)
    assert out.status == "deep-proposed", out.error
    assert out.scope_needed == 3
    line = next(r for r in out.reports if "helper.md" in r)
    assert "-helper: unrelated notes" in line and "+the checkout neighbour, edited" in line
    assert (plain / "dotclaude" / "skills" / "helper.md").read_text(encoding="utf-8") == "helper: unrelated notes\n"


def test_a_checkout_without_a_repository_never_becomes_a_worktree_of_a_parent_repository(tmp_path):
    """Found by the M17 test's first run: `git worktree add` run from a
    plain directory searches UPWARD, and under the temp tree it found the
    HOME repository and made the sandbox a checkout of ~/.claude. A
    checkout that is not a repository is copied, and the repository above
    it is never touched."""
    from dazzle_claude_config import aisandbox
    from dazzle_claude_config.manifest import Entry
    parent = tmp_path / "parent"
    (parent / "plain" / "dotclaude" / "skills").mkdir(parents=True)
    sp.run(["git", "init", "-q", "-b", "main", str(parent)], check=True)
    (parent / "plain" / "dotclaude" / "skills" / "s.md").write_text("theirs\n", encoding="utf-8")
    _git(parent, "add", "-A")
    _git(parent, "commit", "-qm", "the parent repository")
    entry = Entry(repo="dotclaude/skills", strategy="copy", territory="dotclaude", target="skills")
    sb = aisandbox.prepare(workdir=tmp_path / "ws" / "x.ai-deep", checkout_repo=parent / "plain",
                           live_root=None, entry=entry, rel="s.md", mechanical=b"merged\n")
    try:
        assert sb.worktree is False and "not a repository" in sb.note
        assert not (sb.checkout / ".git").exists()
        assert len(_git(parent, "worktree", "list").strip().splitlines()) == 1     # the parent alone
        assert sb.payload_file.read_bytes() == b"merged\n"
    finally:
        aisandbox.release(sb)
    assert len(_git(parent, "worktree", "list").strip().splitlines()) == 1


def test_a_recipe_outcome_reads_as_recipe_by_default_M19():
    """v0.6.4 sweep, survivor M19: every outcome the recipe builds relies on
    the default; the report and the record key on it."""
    from dazzle_claude_config.aistep import AiOutcome
    assert AiOutcome("no-hunks").kind == "recipe"
    assert AiOutcome("deep-empty", kind="deep").kind == "deep"


def test_build_backend_prefers_the_steps_backend_over_the_options_M20(tmp_path):
    """v0.6.4 sweep, survivor M20: `--ai claude,deep:lmstudio` builds the
    deep step on lmstudio even though the options name claude."""
    from dazzle_claude_config import ailib
    opts = _opts({"user": tmp_path}, backend="claude")
    assert ailib.build_backend(opts, "lmstudio").spec.name == "lmstudio"
    assert ailib.build_backend(opts).spec.name == "claude"
    assert ailib.build_backend(opts, None).spec.name == "claude"


# -- the mechanical result and the record ------------------------------------------------

def test_without_a_mechanical_result_the_step_is_skipped(tmp_path, fakes):
    w = _world(tmp_path)
    out = _deep(w, scope=1, mechanical="")
    assert out.status == "deep-skipped" and _Tools.calls == 0


def test_a_second_deep_answer_is_appended_and_numbered(tmp_path, fakes):
    from dazzle_claude_config import airecord
    w = _world(tmp_path)
    _Tools.script = [("checkout/dotclaude/skills/merged.py", FIXED_BROKEN)]
    first = _deep(w, scope=1)
    second = _deep(w, backend="lmstudio", scope=1)
    assert first.variant == airecord.proposal_path(w["merged"], 1)
    assert second.variant == airecord.proposal_path(w["merged"], 2)
    rec = airecord.load(airecord.record_path(w["merged"]))
    assert [airecord.answer_kind(a) for a in rec.answers] == ["mechanical", "deep", "deep"] and rec.chosen == 0


def test_the_prompt_names_the_sandbox_layout_the_scope_and_shows_earlier_variants_last(tmp_path, fakes):
    from dazzle_claude_config import airecord
    w = _world(tmp_path)
    earlier = airecord.proposal_path(w["merged"])
    earlier.parent.mkdir(parents=True, exist_ok=True)
    earlier.write_text(MERGED_BROKEN, encoding="utf-8")
    from dazzle_claude_config import aideep, aistep
    out = aideep.deep_step(
        label=w["label"], base=BASE.encode(), ours=OURS.encode(), theirs=THEIRS_BROKEN.encode(),
        mechanical=MERGED_BROKEN.encode(), variants=[earlier], entry=w["entry"], rel=w["rel"],
        checkout_repo=w["co"], live_root=w["live"], opts=_opts(w), step=aistep.AiStep("deep", "claude"),
        scope=2, workdir=w["ws"] / "skills__merged.py.ai-deep", dossier="THE DOSSIER", facts={},
        merged=w["merged"], tripwire=None)
    assert out.status == "deep-empty"
    prompt = _Tools.seen["prompt"]
    assert "checkout/dotclaude/skills/merged.py" in prompt and "live/skills" in prompt
    assert "this file only" in prompt                                        # the scope phrase
    assert "THE DOSSIER" in prompt
    assert prompt.rstrip().endswith("```") and "earlier" in prompt.lower()
    assert prompt.index("THE DOSSIER") < prompt.index("earlier variant")     # shown last


# -- U7: the two branches the coverage run of 2026-09-11 named as never executed ---------

def test_a_single_file_live_component_is_copied_and_is_its_own_neighbour(tmp_path, fakes):
    """An entry whose target is one FILE (a CLAUDE.md), not a directory:
    the sandbox copies the file beside the checkout, and rung 3 knows the
    live copy as a neighbour. Neither branch had ever run."""
    from dazzle_claude_config import aideep, aisandbox
    from dazzle_claude_config.manifest import Entry
    w = _world(tmp_path)
    (w["co"] / "dotclaude" / "CLAUDE.md").write_text("# base\n", encoding="utf-8")
    _git(w["co"], "add", "-A")
    _git(w["co"], "commit", "-qm", "a single-file component")
    (w["live"] / "CLAUDE.md").write_text("# mine\n", encoding="utf-8")
    entry = Entry(repo="dotclaude/CLAUDE.md", strategy="copy", territory="dotclaude", target="CLAUDE.md")
    sb = aisandbox.prepare(workdir=w["ws"] / "dotclaude__CLAUDE.md.ai-deep", checkout_repo=w["co"],
                           live_root=w["live"], entry=entry, rel="", mechanical=b"# merged\n")
    try:
        assert sb.live is not None and sb.live.is_file()
        assert sb.live.read_text(encoding="utf-8") == "# mine\n"
        assert sb.payload_rel == "checkout/dotclaude/CLAUDE.md" and sb.payload_file.read_bytes() == b"# merged\n"
        n = aideep.neighbours_of("CLAUDE.md", entry=entry, rel="", checkout_repo=w["co"], live_root=w["live"])
        assert "live/CLAUDE.md" in n
        assert "checkout/dotclaude/CLAUDE.md" not in n                 # the payload is never its own neighbour
    finally:
        aisandbox.release(sb)
    assert (w["live"] / "CLAUDE.md").read_text(encoding="utf-8") == "# mine\n"   # the real file untouched


def test_a_stale_sandbox_from_an_interrupted_run_is_removed_by_the_next_prepare(tmp_path, fakes):
    """A run interrupted after `prepare` leaves a worktree registered in the
    source repo and a directory in the workspace. The next `prepare` at the
    same workdir removes both -- the worktree through git -- and builds a
    fresh one, so the source repo never accumulates dead worktrees."""
    from dazzle_claude_config import aisandbox
    w = _world(tmp_path)
    workdir = w["ws"] / "skills__merged.py.ai-deep"
    first = aisandbox.prepare(workdir=workdir, checkout_repo=w["co"], live_root=w["live"],
                              entry=w["entry"], rel=w["rel"], mechanical=MERGED_BROKEN.encode())
    assert first.worktree
    (workdir / "leftover.txt").write_text("from an interrupted run\n", encoding="utf-8")
    assert _git(w["co"], "worktree", "list", "--porcelain").count("worktree ") == 2   # the repo and the sandbox
    second = aisandbox.prepare(workdir=workdir, checkout_repo=w["co"], live_root=w["live"],
                               entry=w["entry"], rel=w["rel"], mechanical=MERGED_BROKEN.encode())
    try:
        assert not (workdir / "leftover.txt").exists()
        assert second.worktree and second.payload_file.read_bytes() == MERGED_BROKEN.encode()
        assert _git(w["co"], "worktree", "list", "--porcelain").count("worktree ") == 2   # still exactly one sandbox
    finally:
        aisandbox.release(second)
    assert _git(w["co"], "worktree", "list", "--porcelain").count("worktree ") == 1
