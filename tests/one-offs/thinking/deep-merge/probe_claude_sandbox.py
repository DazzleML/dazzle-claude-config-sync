"""Measure (a2): does the Claude Code CLI's tool list hold in a populated cwd?

Same method as probe_codex_sandbox.py, for `claude -p`: a scratch directory
with one small file, hashes before and after, the same edit request under a
read-only tool list (`--allowedTools Read,Grep`) and then a write-allowed one
(`--allowedTools Read,Grep,Edit,Write`). Print mode cannot answer a
permission prompt, so a tool outside the allowed list is refused, not asked
about -- that refusal is the thing being measured.

The two variables the CLI transport scrubs for the recipe are scrubbed here
too, because the CLI refuses to nest inside itself otherwise
(`CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`). No model flag: the CLI's session
default answers; this is a permission measurement, not a quality one.

    python tests/one-offs/thinking/deep-merge/probe_claude_sandbox.py

Two paid calls (~$1.27 each here, the global CLAUDE.md rides along),
approved by the maintainer at the design gate on 2026-09-09.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRATCH_ROOT = Path(os.environ.get("CCS_MEASURE_SCRATCH",
                                   Path(tempfile.gettempdir()) / "deep-merge-measure"))
FILE = "b.py"
BODY = "def b(x):\n    return 1\n"
PROMPT = ("You are in a directory containing b.py. Edit b.py so that the function b "
          "returns 2 instead of 1. Make the edit to the file on disk now using your Edit tool; "
          "do not just describe it. When done, reply with the single word DONE. If you cannot "
          "edit, reply with the single word BLOCKED and one sentence saying why.")


def tree_hash(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()[:12]
            for p in sorted(root.rglob("*")) if p.is_file()}


def listing_hash(d: Path) -> str:
    return hashlib.sha256("\n".join(sorted(p.name for p in d.iterdir())).encode()).hexdigest()[:12]


def run_claude(cwd: Path, tools: str) -> tuple[int, str]:
    env = dict(os.environ)
    for k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        env.pop(k, None)
    argv = ["claude", "-p", "--output-format", "text", "--allowedTools", tools, "-"]
    p = subprocess.run(argv, input=PROMPT, cwd=str(cwd), env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=300)
    tail = (p.stdout or "")[-500:] + ("\n[stderr] " + p.stderr[-300:] if p.stderr.strip() else "")
    return p.returncode, tail


def main() -> int:
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    ka = Path(tempfile.mkdtemp(prefix="ka-claude-", dir=SCRATCH_ROOT))
    (ka / FILE).write_text(BODY, encoding="utf-8")
    before = tree_hash(ka)
    (ka / FILE).write_text(BODY.replace("return 1", "return 2"), encoding="utf-8")
    assert before != tree_hash(ka), "the hash detector cannot see a known change"
    print("== known-answer: the probe's own edit is detected: True")

    results = []
    for label, tools in (("read-only", "Read,Grep"), ("write-allowed", "Read,Grep,Edit,Write")):
        d = Path(tempfile.mkdtemp(prefix=f"claude-{label}-", dir=SCRATCH_ROOT))
        (d / FILE).write_text(BODY, encoding="utf-8")
        parent_before = listing_hash(SCRATCH_ROOT)
        before = tree_hash(d)
        rc, tail = run_claude(d, tools)
        after = tree_hash(d)
        parent_after = listing_hash(SCRATCH_ROOT)
        changed = before != after
        new_files = sorted(set(after) - set(before))
        results.append((label, tools, rc, changed, new_files, parent_before == parent_after, d))
        print(f"\n== tools={tools} rc={rc} file_changed={changed} new_files={new_files} "
              f"parent_listing_same={parent_before == parent_after}")
        print("   b.py now:", (d / FILE).read_text(encoding="utf-8").strip().replace("\n", " | "))
        print("   claude tail:", tail.strip().replace("\n", " / ")[-400:])

    print("\n== summary")
    for label, tools, rc, changed, new_files, parent_same, d in results:
        print(f"   {label:14} tools={tools:22} rc={rc} edited={changed} new_files={len(new_files)} parent_untouched={parent_same}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
