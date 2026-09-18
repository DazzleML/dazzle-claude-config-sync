"""Enumerate what rung 1 looks like on the real workspace (U2 of #64).

Decision this feeds: whether the region definitions -- Markdown from each
heading to the next of any level, code by column-0 blocks, paragraphs
otherwise -- give the deep step a rung-1 territory a person would agree
with, on the maintainer's real merge inputs, BEFORE the deep step (U4) is
built on them. The maintainer reads the output.

Method: for every `<label>.merged.inputs/{base,ours,theirs}` under the
real merge workspace (default `~/claude/merge/ccs`), COPY the three files
into a scratch directory, compute git's mechanical result there
(`git merge-file --diff3 -p`, markers left in place when the merge is not
clean), then split the mechanical text into regions by the label's suffix
and mark the anchored ones (the spans that differ from the base). Report
per input set: the suffix, the line counts, the conflict-hunk count, the
regions (anchored / total), and the anchored regions by title with their
size and how many of their lines an anchor covers. Nothing under the
workspace is written; the copies live under the scratch root.

    python tests/one-offs/thinking/deep-merge/enumerate_rung1.py [workspace] [--out FILE]

Output: `enumerate_rung1__output_<date>.md` beside this script (kept in
the commit, so the reading survives).
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from dazzle_claude_config import airung            # noqa: E402

DEFAULT_WS = Path(os.path.expanduser("~")) / "claude" / "merge" / "ccs"
SCRATCH_ROOT = Path(os.environ.get("CCS_MEASURE_SCRATCH",
                                   Path(tempfile.gettempdir()) / "deep-merge-measure"))


def mechanical(base: Path, ours: Path, theirs: Path, scratch: Path) -> tuple[str, int]:
    """git's result and its conflict-hunk count, computed on COPIES."""
    scratch.mkdir(parents=True, exist_ok=True)
    for name, src in (("base", base), ("ours", ours), ("theirs", theirs)):
        shutil.copyfile(src, scratch / name)
    p = subprocess.run(["git", "merge-file", "--diff3", "-p", "ours", "base", "theirs"],
                       cwd=str(scratch), capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    hunks = p.returncode if 0 <= p.returncode < 128 else -1
    return p.stdout, hunks


def covered(span_list, region) -> int:
    n = 0
    for a1, a2 in span_list:
        lo, hi = max(a1, region.start), min(a2, region.end)
        if hi > lo:
            n += hi - lo
        elif a1 == a2 and region.start <= a1 <= region.end:
            n += 0
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("workspace", nargs="?", default=str(DEFAULT_WS))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    ws = Path(args.workspace)
    sets = sorted(p for p in ws.glob("*.merged.inputs") if (p / "base").is_file()
                  and (p / "ours").is_file() and (p / "theirs").is_file())
    if not sets:
        print(f"no input sets under {ws}", file=sys.stderr)
        return 2
    stamp = dt.date.today().isoformat()
    out = Path(args.out) if args.out else Path(__file__).with_name(f"enumerate_rung1__output_{stamp}.md")
    scratch = Path(tempfile.mkdtemp(prefix="enumerate-rung1-", dir=str(SCRATCH_ROOT)))
    lines = [f"# What rung 1 looks like on the real workspace -- {stamp}", "",
             f"Workspace: `{ws}` ({len(sets)} input sets, read only; copies under `{scratch}`).",
             "Regions per `airung.split_regions` (by suffix); anchors per `airung.anchors` (the spans "
             "of git's mechanical result that differ from the base). A conflict hunk count above 0 "
             "means the mechanical text still carries diff3 markers, which the regions include as text.",
             "", "| input set | suffix | base / mech lines | hunks | regions anchored/total | "
             "anchored lines / mech lines |", "|---|---|---|---|---|---|"]
    detail: list[str] = []
    totals = {"sets": 0, "regions": 0, "anchored": 0, "hunks": 0}
    by_suffix: dict[str, list[int]] = {}
    for d in sets:
        label = d.name[:-len(".merged.inputs")].replace("__", "/")
        base_t = (d / "base").read_text(encoding="utf-8", errors="replace")
        mech_t, hunks = mechanical(d / "base", d / "ours", d / "theirs", scratch / d.name)
        regions = airung.split_regions(mech_t, label)
        spans = airung.anchors(base_t, mech_t)
        anchored = [r for r in regions if any(airung._overlaps(s, r) for s in spans)]
        mech_n = len(mech_t.splitlines())
        anchored_lines = sum(r.end - r.start for r in anchored)
        suffix = airung._suffix(label) or "(none)"
        totals["sets"] += 1
        totals["regions"] += len(regions)
        totals["anchored"] += len(anchored)
        totals["hunks"] += max(hunks, 0)
        by_suffix.setdefault(suffix, [0, 0, 0, 0])
        by_suffix[suffix][0] += 1
        by_suffix[suffix][1] += len(regions)
        by_suffix[suffix][2] += len(anchored)
        by_suffix[suffix][3] += mech_n
        lines.append(f"| `{label}` | {suffix} | {len(base_t.splitlines())} / {mech_n} | {hunks} | "
                     f"{len(anchored)}/{len(regions)} | {anchored_lines} / {mech_n} |")
        detail.append(f"### `{label}`")
        detail.append("")
        if not anchored:
            detail.append("no anchored region: the mechanical result equals the base "
                          "(or differs only where no region tiles it).")
        for r in anchored:
            title = r.title or r.kind
            detail.append(f"- **{title}** ({r.kind}, lines {r.start + 1}-{r.end}, {r.end - r.start} lines; "
                          f"{covered(spans, r)} changed by the merge)")
        detail.append("")
    lines += ["", f"**Totals:** {totals['sets']} sets, {totals['regions']} regions, "
              f"{totals['anchored']} anchored (rung-1 territory), {totals['hunks']} conflict hunks.", "",
              "| suffix | sets | regions | anchored | mechanical lines |", "|---|---|---|---|---|"]
    for suffix, (n, reg, anc, ml) in sorted(by_suffix.items()):
        lines.append(f"| {suffix} | {n} | {reg} | {anc} | {ml} |")
    lines += ["", "## The anchored regions, per input set", ""] + detail
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:len(sets) + 8]))
    print(f"\nwritten: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
