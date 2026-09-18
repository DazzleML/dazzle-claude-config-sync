"""Build the scratch world the `--ai` human checklist runs against.

Shape (the default): a checkout with two commits, the second being the
payload's change, and a live file that rewrote the same line differently.
The inferred base is the first commit, so the merge has exactly one
conflict hunk -- one line against one line, which is the paragraph case
the sub-line report exists for, and the shape the real workspace's only
conflict had.

    --one-commit   history of one, so nothing in it equals the live file
                   and `--ai` refuses for want of a base (checklist 1.2)
    --dissimilar   the two rewrites share almost no words, so dropping the
                   live line is NOT superseded and needs a cited rule
                   (checklist 2.2)

Usage:  python tests/one-offs/thinking/build_ai_world.py <dir> [flags]
It prints the three overrides to paste in front of every `ccs` command.
"""
from __future__ import annotations

import argparse
import json
import subprocess as sp
import sys
from pathlib import Path

GIT_ID = ["-c", "user.email=t@t.invalid", "-c", "user.name=t", "-c", "commit.gpgsign=false"]

MANIFEST = {
    "manifest_version": 1,
    "territories": {"dotclaude": {"root_var": "CLAUDE_DIR", "repo_dir": "dotclaude"}},
    "entries": [{"repo": "dotclaude/skills", "territory": "dotclaude",
                 "target": "skills", "strategy": "copy"}],
}

HEAD_ = "# Deletion\n\n"
TAIL = "\nEvery box keeps its own recovery folder.\n"
BASE_LINE = "Deletions are confirmed by a person before the file is removed.\n"
THEIRS_LINE = ("Deletions are confirmed by a person before the file is removed, and the "
               "confirmation is recorded in the receipt.\n")
OURS_LINE = ("Deletions are confirmed by a person on this box before the file is removed.\n")
OURS_FAR = ("Nothing is removed here at all: retired files are staged to the recovery folder "
            "and swept by hand.\n")


def build(root: Path, one_commit: bool, dissimilar: bool) -> dict:
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

    target = co / "dotclaude" / "skills" / "s.md"
    history = [HEAD_ + THEIRS_LINE + TAIL] if one_commit else [
        HEAD_ + BASE_LINE + TAIL, HEAD_ + THEIRS_LINE + TAIL]
    for i, text in enumerate(history):
        target.write_bytes(text.encode())
        if i == 0:
            git("add", "-A")
            git("commit", "-qm", "the payload, before this change")
        else:
            git("commit", "-qam", "the payload's change to the deletion rule")
    ours = OURS_FAR if dissimilar else OURS_LINE
    (live / "skills" / "s.md").write_bytes((HEAD_ + ours + TAIL).encode())
    return dict(co=co, live=live, user=user)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dir", help="where to build it (must not exist)")
    ap.add_argument("--one-commit", action="store_true", help="no ancestor -- --ai refuses")
    ap.add_argument("--dissimilar", action="store_true", help="a drop needs a cited rule")
    args = ap.parse_args(argv)
    root = Path(args.dir).expanduser()
    if root.exists():
        print(f"{root} exists -- remove it first (dz safedel) so the world is clean")
        return 2
    w = build(root, args.one_commit, args.dissimilar)
    print(f"built: {root}")
    print("  the payload's change and your box's change touch the same line;", end=" ")
    print("no ancestor" if args.one_commit else "the ancestor is the first commit")
    print("\nPut this in front of every ccs command (<OVR> in the checklist):\n")
    ovr = (f'--checkout-dir "{w["co"]}" --claude-dir "{w["live"]}" '
           f'--user-claude "{w["user"]}" --no-fetch')
    print(f"  {ovr}\n")
    print("So a full line reads:\n")
    print(f'  python -m dazzle_claude_config {ovr} merge skills/s.md --ai --no-launch\n')
    print("(or `ccs` in place of `python -m dazzle_claude_config` if it is installed)")
    print(f"\nAfterwards: dz safedel \"{root}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
