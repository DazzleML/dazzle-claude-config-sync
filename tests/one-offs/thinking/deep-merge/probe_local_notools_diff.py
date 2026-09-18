"""Measure (b): can the local model, with no tools, return an applicable diff
for the b()/c() case -- and an EMPTY one when nothing is wrong?

Decision this feeds: whether the deep merge's no-tools form (the design's
candidate E, for server backends over openai_compat) exists at all, and
whether the golden set of this feature needs the empty-diff fixtures the
design predicts (a model that invents work to justify itself).

The fixture, the maintainer's own example made concrete:

    base    a() -> b() -> c(); c returns an int
    ours    Bob changes b():   v = c(x); return v * 2      (assumes an int)
    theirs  Charlie changes c(): returns the tuple (x + 1, x - 1)

`git merge-file --diff3` merges the two cleanly (asserted: no markers) and
the result is wrong without erroring: `(x + 1, x - 1) * 2` is tuple
repetition. The control arm: Charlie returns a plain int instead, the
merge is clean AND right, and the correct answer is an empty diff.

Method: the merged file plus both unified diffs from the base go to the
model through the real library (`ailib.build_backend`, the lmstudio preset,
`Request(schema=None)` so no answer schema is enforced); the reply's diff is
`git apply --check`ed against a scratch copy of the merged file, then
applied and executed. Known-answer case: a hand-written correct diff must
apply, and the merged arm's `a(3)` must be the wrong value before and the
right value after.

    python tests/one-offs/thinking/deep-merge/probe_local_notools_diff.py

Free: the server at 127.0.0.1:1234 is up with qwen3.8-27b-uncensored
loaded; nothing else is loaded; no GPU load is triggered (the preset names
no model, so the transport uses what is loaded).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from dazzle_claude_config import ailib                 # noqa: E402
from dazzle_claude_config.aistep import AiOptions      # noqa: E402

SCRATCH_ROOT = Path(os.environ.get("CCS_MEASURE_SCRATCH",
                                   Path(tempfile.gettempdir()) / "deep-merge-measure"))

BASE = """def c(x):
    return x + 1


def b(x):
    return c(x)


def a(x):
    return b(x)
"""
OURS = BASE.replace("def b(x):\n    return c(x)\n", "def b(x):\n    v = c(x)\n    return v * 2\n")
THEIRS_BROKEN = BASE.replace("def c(x):\n    return x + 1\n", "def c(x):\n    return (x + 1, x - 1)\n")
THEIRS_FINE = BASE.replace("def c(x):\n    return x + 1\n", "def c(x):\n    return x + 2\n")

PROMPT = """You are reviewing the result of a three-way merge of ONE Python file. Git merged it without conflicts: Bob and Charlie changed different regions. Your job is to say whether the two changes still make sense TOGETHER, and if not, to fix the merged file with the smallest edit.

Reply with exactly one fenced ```diff block containing a unified diff against the MERGED file below (the file is named merged.py; use `--- a/merged.py` and `+++ b/merged.py` headers and correct @@ hunk headers). If the merged file is already correct and consistent, reply with an EMPTY diff block:

```diff
```

Do not explain outside the block.

## Bob's change (diff from the common base)
```diff
{ours_diff}
```

## Charlie's change (diff from the common base)
```diff
{theirs_diff}
```

## The merged file, merged.py
```python
{merged}
```
"""


def git(*args: str, cwd: Path, input: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), input=input, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def build(theirs: str, tag: str) -> tuple[Path, str, str, str]:
    d = Path(tempfile.mkdtemp(prefix=f"notools-{tag}-", dir=SCRATCH_ROOT))
    for name, body in (("base.py", BASE), ("ours.py", OURS), ("theirs.py", theirs)):
        (d / name).write_text(body, encoding="utf-8")
    m = git("merge-file", "--diff3", "-p", "ours.py", "base.py", "theirs.py", cwd=d)
    merged = m.stdout
    assert "<<<<<<<" not in merged and ">>>>>>>" not in merged, "the merge is not clean -- the fixture is wrong"
    (d / "merged.py").write_text(merged, encoding="utf-8")
    ours_diff = git("diff", "--no-index", "--", "base.py", "ours.py", cwd=d).stdout
    theirs_diff = git("diff", "--no-index", "--", "base.py", "theirs.py", cwd=d).stdout
    return d, merged, ours_diff, theirs_diff


def run_merged(d: Path) -> str:
    p = subprocess.run([sys.executable, "-c", "import merged; print(repr(merged.a(3)))"],
                       cwd=str(d), capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (p.stdout.strip() or p.stderr.strip().splitlines()[-1] if p.stderr.strip() else p.stdout.strip())


def extract_diff(text: str) -> str:
    m = re.search(r"```diff\s*\n(.*?)```", text, re.S)
    if m:
        return m.group(1)
    return text if text.lstrip().startswith(("---", "diff --git")) else ""


def apply_check(d: Path, diff: str) -> tuple[bool, str]:
    if not diff.strip():
        return True, "(empty diff)"
    patch = d / "answer.patch"
    patch.write_text(diff if diff.endswith("\n") else diff + "\n", encoding="utf-8")
    p = git("apply", "--check", "--unsafe-paths", str(patch), cwd=d)
    return p.returncode == 0, (p.stderr.strip() or p.stdout.strip() or "ok")


def apply_for_real(d: Path, diff: str) -> bool:
    patch = d / "answer.patch"
    p = git("apply", "--unsafe-paths", str(patch), cwd=d)
    return p.returncode == 0


def touches(diff: str) -> dict[str, bool]:
    body = "\n".join(l for l in diff.splitlines() if l.startswith(("+", "-")) and not l.startswith(("+++", "---")))
    return {"b()": "def b" in body or "v * 2" in body or "return v" in body,
            "c()": "def c" in body or "x + 1" in body or "x - 1" in body,
            "a()": "def a" in body}


def main() -> int:
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    opts = AiOptions(rules_dir=SCRATCH_ROOT, prompts_dir=SCRATCH_ROOT, cache_dir=SCRATCH_ROOT / "cache",
                     backend="lmstudio", timeout=180)
    # -- known-answer FIRST (needs no model): the fixture is wrong-then-right, and a
    # correct diff applies through the same path the model's answer will take ------
    d, merged, ours_diff, theirs_diff = build(THEIRS_BROKEN, "ka")
    wrong = run_merged(d)
    hand = ("--- a/merged.py\n+++ b/merged.py\n@@ -5,4 +5,4 @@\n def b(x):\n-    v = c(x)\n+    v, _ = c(x)\n"
            "     return v * 2\n \n")
    ok, why = apply_check(d, hand)
    assert ok, f"known-answer diff does not apply: {why}"
    apply_for_real(d, hand)
    right = run_merged(d)
    print(f"== known-answer: merged a(3) before={wrong} (tuple repetition) after hand fix={right}")
    assert wrong.startswith("(") and right == "8", "the known-answer case did not behave as the fixture claims"
    dc, _, _, _ = build(THEIRS_FINE, "ka-control")
    print(f"== known-answer control: the fine arm's merged a(3)={run_merged(dc)} (a plain int; nothing to fix)")

    backend = ailib.build_backend(opts)
    ready = backend.probe()
    print("== backend:", backend.identity, "|", ready.reason[:80])
    if not ready.ok:
        print("== SERVER DOWN: the model arms did not run; the fixture and the apply path are validated above. "
              "Start LM Studio's server with the loaded model and re-run.")
        return 2

    rows = []
    for tag, theirs, expect in (("broken", THEIRS_BROKEN, "a fix touching b() (or c())"),
                                ("control", THEIRS_FINE, "an EMPTY diff")):
        d, merged, ours_diff, theirs_diff = build(theirs, tag)
        before = run_merged(d)
        prompt = PROMPT.format(ours_diff=ours_diff, theirs_diff=theirs_diff, merged=merged)
        resp = backend.invoke(ailib.Request(prompt=prompt, schema=None, timeout=180))
        text = resp.text or ""
        diff = extract_diff(text)
        applies, why = apply_check(d, diff)
        after = None
        if applies and diff.strip():
            apply_for_real(d, diff)
            after = run_merged(d)
        t = touches(diff)
        rows.append((tag, resp.status, round(resp.elapsed, 1), bool(diff.strip()), applies, why[:60], t, before, after, expect))
        print(f"\n== arm={tag} status={resp.status} elapsed={resp.elapsed:.1f}s model={resp.model_used}")
        print(f"   expected: {expect}")
        print(f"   reply head: {text[:300].replace(chr(10), ' / ')}")
        print(f"   diff non-empty={bool(diff.strip())} applies={applies} ({why[:80]}) touches={t}")
        print(f"   a(3): before={before} after={after}")

    print("\n== summary (arm, status, s, non-empty, applies, touches, a(3) before -> after, expected)")
    for r in rows:
        print("  ", r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
