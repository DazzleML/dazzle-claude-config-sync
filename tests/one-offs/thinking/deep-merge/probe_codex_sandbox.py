"""Measure (a): does the codex CLI's sandbox hold in a populated cwd?

Decision this feeds: the deep merge's build step 4 (the transport's
populated-cwd mode) and its acceptance check C4 -- "after any deep run the
real trees are hash-identical". If `codex exec -s read-only` cannot be
stopped from writing, the sandbox is ccs's to enforce (a copy the model may
scribble on); if it holds, the CLI's own flag is one layer and ccs's copy is
the second.

Method: a scratch directory with one small file; a hash of every file in
the scratch AND a listing hash of its parent, taken before and after each
call; the same prompt in each sandbox mode asking for an edit. Known-answer
case: the probe itself edits the file once and confirms the hash detection
sees it (a detector that cannot see a known change proves nothing).

    python tests/one-offs/thinking/deep-merge/probe_codex_sandbox.py

Costs two or three codex calls on the maintainer's account (permitted for
this run). Never touches ~/claude, ~/.claude or the checkout.
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
          "returns 2 instead of 1. Make the edit to the file on disk now; do not just "
          "describe it. When done, reply with the single word DONE.")


def tree_hash(root: Path) -> dict[str, str]:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
    return out


def listing_hash(d: Path) -> str:
    names = sorted(p.name for p in d.iterdir())
    return hashlib.sha256("\n".join(names).encode()).hexdigest()[:12]


def run_codex(cwd: Path, sandbox: str) -> tuple[int, str]:
    argv = ["codex", "exec", "-s", sandbox, "--skip-git-repo-check", "-"]
    p = subprocess.run(argv, input=PROMPT, cwd=str(cwd), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=300)
    tail = (p.stdout or "")[-600:] + ("\n[stderr] " + p.stderr[-400:] if p.stderr.strip() else "")
    return p.returncode, tail


def main() -> int:
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    print("== codex exec --help: the sandbox modes it names")
    h = subprocess.run(["codex", "exec", "--help"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace").stdout
    for line in h.splitlines():
        if "sandbox" in line.lower() and ("possible" in line.lower() or "values" in line.lower() or "[" in line):
            print("   ", line.strip()[:160])

    # known-answer case: the detector sees a change the probe makes itself
    ka = Path(tempfile.mkdtemp(prefix="ka-", dir=SCRATCH_ROOT))
    (ka / FILE).write_text(BODY, encoding="utf-8")
    before = tree_hash(ka)
    (ka / FILE).write_text(BODY.replace("return 1", "return 2"), encoding="utf-8")
    after = tree_hash(ka)
    print("== known-answer: the probe's own edit is detected:", before != after)
    assert before != after, "the hash detector cannot see a known change -- the method is broken"

    results = []
    for sandbox in ("read-only", "workspace-write"):
        d = Path(tempfile.mkdtemp(prefix=f"codex-{sandbox}-", dir=SCRATCH_ROOT))
        (d / FILE).write_text(BODY, encoding="utf-8")
        parent_before = listing_hash(SCRATCH_ROOT)
        before = tree_hash(d)
        rc, tail = run_codex(d, sandbox)
        after = tree_hash(d)
        parent_after = listing_hash(SCRATCH_ROOT)
        changed = before != after
        new_files = sorted(set(after) - set(before))
        results.append((sandbox, rc, changed, new_files, parent_before == parent_after, d))
        print(f"\n== sandbox={sandbox} rc={rc} file_changed={changed} new_files={new_files} "
              f"parent_listing_same={parent_before == parent_after}")
        print("   b.py now:", (d / FILE).read_text(encoding="utf-8").strip().replace("\n", " | "))
        print("   codex tail:", tail.strip().replace("\n", " / ")[-500:])

    print("\n== summary")
    for sandbox, rc, changed, new_files, parent_same, d in results:
        print(f"   {sandbox:16} rc={rc} edited={changed} new_files={len(new_files)} parent_untouched={parent_same}  ({d})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
