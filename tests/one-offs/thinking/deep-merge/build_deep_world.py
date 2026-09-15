"""Build the scratch world the deep-merge human checklist runs against.

Every case is a checkout with two commits (the base, then the payload's
change), a neighbour in the same component, a far file, and a live file
holding this box's change -- the same shapes the deep golden set
(tests/test_golden_ai_deep.py) proves canned, laid out on disk so a person
can run the real command against a real backend.

    --case python             the founding case: Bob doubles what c() returns,
                              Charlie makes c() return a pair; git merges both
                              cleanly and a(3) is (4, 2, 4, 2)        (default)
    --case python-control     Charlie's c() still returns an int; nothing is wrong
    --case markdown           a runbook: Bob adds a step citing "the report",
                              Charlie renames it "the summary" elsewhere
    --case markdown-control   Charlie's change does not contradict Bob's step
    --case conflict           pass 1's shape: both sides rewrote the same line,
                              so there is one conflict-hunk for the recipe

Usage:  python tests/one-offs/thinking/deep-merge/build_deep_world.py <dir> [--case NAME]
It prints the three overrides to paste in front of every `ccs` command.
Nothing here touches ~/.claude, ~/claude or any real checkout.
"""
from __future__ import annotations

import argparse
import json
import subprocess as sp
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[3]))          # tests/, for bc_fixture and the golden set's texts

from bc_fixture import BASE, OURS, THEIRS_BROKEN, THEIRS_FINE  # noqa: E402

GIT_ID = ["-c", "user.email=t@t.invalid", "-c", "user.name=t", "-c", "commit.gpgsign=false"]

MANIFEST = {
    "manifest_version": 1,
    "territories": {"dotclaude": {"root_var": "CLAUDE_DIR", "repo_dir": "dotclaude"}},
    "entries": [{"repo": "dotclaude/skills", "territory": "dotclaude",
                 "target": "skills", "strategy": "copy"}],
}

BASE_MD = """# Runbook

## Terms

The report is the file `out.md`.
It is regenerated on every build.

## Steps

1. Run the build.
2. Check the log.

## Notes

Nothing yet.
"""
OURS_MD = BASE_MD.replace("2. Check the log.\n", "2. Check the log.\n3. Open the report.\n")
THEIRS_MD = BASE_MD.replace("The report is the file", "The summary is the file")
THEIRS_FINE_MD = BASE_MD.replace("It is regenerated on every build.",
                                 "It is regenerated on every build and kept beside the log.")

# pass 1's shape: one line rewritten differently on each side
HEAD_ = "# Deletion\n\n"
TAIL = "\nEvery box keeps its own recovery folder.\n"
BASE_LINE = "Deletions are confirmed by a person before the file is removed.\n"
THEIRS_LINE = ("Deletions are confirmed by a person before the file is removed, and the "
               "confirmation is recorded in the receipt.\n")
OURS_LINE = "Deletions are confirmed by a person on this box before the file is removed.\n"

CASES = {
    "python": ("s.py", BASE, OURS, THEIRS_BROKEN,
               "Bob doubles what c() returns; Charlie makes c() return a pair -- clean, and wrong"),
    "python-control": ("s.py", BASE, OURS, THEIRS_FINE,
                       "Bob doubles what c() returns; Charlie's c() still returns an int -- clean, and right"),
    "markdown": ("s.md", BASE_MD, OURS_MD, THEIRS_MD,
                 "Bob adds a step citing the report; Charlie renames it the summary -- clean, and wrong"),
    "markdown-control": ("s.md", BASE_MD, OURS_MD, THEIRS_FINE_MD,
                         "Bob adds a step; Charlie's change does not contradict it -- clean, and right"),
    "conflict": ("s.md", HEAD_ + BASE_LINE + TAIL, HEAD_ + OURS_LINE + TAIL, HEAD_ + THEIRS_LINE + TAIL,
                 "both sides rewrote the same line -- one conflict-hunk, the recipe's"),
}


def build(root: Path, case: str) -> dict:
    name, base, ours, theirs, _ = CASES[case]
    co, live, user = root / "checkout", root / "live", root / "user"
    (co / "dotclaude" / "skills").mkdir(parents=True)
    (live / "skills").mkdir(parents=True)
    user.mkdir(parents=True)
    (co / "ccs-manifest.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    sp.run(["git", "init", "-q", "-b", "main", str(co)], check=True)

    def git(*a):
        r = sp.run(["git", *GIT_ID, "-C", str(co), *a], capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f"git {a}: {r.stderr}")

    target = co / "dotclaude" / "skills" / name
    target.write_text(base, encoding="utf-8", newline="\n")
    (co / "dotclaude" / "skills" / "helper.md").write_text("helper: notes the payload does not cite\n",
                                                          encoding="utf-8", newline="\n")
    (co / "README.md").write_text("a far file\n", encoding="utf-8", newline="\n")
    git("add", "-A")
    git("commit", "-qm", "the payload, before this change")
    target.write_text(theirs, encoding="utf-8", newline="\n")
    git("commit", "-qam", "the payload's change (Charlie)")
    (live / "skills" / name).write_text(ours, encoding="utf-8", newline="\n")
    (live / "skills" / "helper.md").write_text("helper: notes the payload does not cite\n",
                                              encoding="utf-8", newline="\n")
    return dict(co=co, live=live, user=user, name=name)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir", help="where to build it (must not exist)")
    ap.add_argument("--case", choices=sorted(CASES), default="python")
    args = ap.parse_args(argv)
    root = Path(args.dir).expanduser()
    if root.exists():
        print(f"{root} exists -- remove it first (dz safedel) so the world is clean")
        return 2
    w = build(root, args.case)
    print(f"built: {root}  ({args.case}: {CASES[args.case][4]})")
    print("\nPut this in front of every ccs command (<OVR> in the checklist):\n")
    ovr = (f'--checkout-dir "{w["co"]}" --claude-dir "{w["live"]}" '
           f'--user-claude "{w["user"]}" --no-fetch')
    print(f"  {ovr}\n")
    print("So a full line reads:\n")
    print(f'  python -m dazzle_claude_config {ovr} merge skills/{w["name"]} --ai lmstudio,deep --no-launch\n')
    print("(or `ccs` in place of `python -m dazzle_claude_config` if it is installed)")
    print(f"\nAfterwards: dz safedel \"{root}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
