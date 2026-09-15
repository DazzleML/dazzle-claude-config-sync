"""POC: can dazzle-lib's Continuum / ContinuumSpace express the deep merge's
latitude rules as DATA, with no special-case branch?  (2026-09-15, for the
latitude dev-workflow-process; #64 mid-run at U6, nothing here ships.)

The proposal (the maintainer, 2026-09-15): latitude has two axes -- WHERE an
edit may land (the rung ladder) and how FREELY the model may write -- settable
apart from what it may LOOK at, and shaped like a dazzle-lib continuum. This
script builds the smallest thing that could show that shape does NOT fit.

Predictions, written before anything ran:

  A1  the verdict gate in aideep.deep_step -- `verdict.needed > scope` is
      deep-failed (aideep.py:326-328) -- is exactly `WHERE.passes(needed,
      allowed)` on a monopole Continuum ranked none=0 hunk=1 file=2
      neighbours=3 project=4.            Predict: 25 of 25 (allowed, needed)
      pairs agree.
  A2  the no-tools cap -- `scope >= 3 and not tools` is refused before any
      call (aideep.py:255-259) -- is the SAME predicate against a ceiling
      carried as payload data on the composed space (no-tools -> file,
      tools -> project).                 Predict: 10 of 10 (form, allowed)
      pairs agree, no branch of ours.
  A3  CONTROL, predicted to FAIL the gate: the point change=project with
      look=file must be refused, i.e. `WHERE.passes("project", "file")` is
      False. If it passes, the predicate runs the wrong way and the method
      is broken: nothing above counts.
  A3s the STRONG claim -- "the space itself marks a cross-axis point
      impossible" -- predicted REFUTED: a product ContinuumSpace holds axes
      and payloads and declares cross-axis navigation undefined by design;
      the constraint is one predicate the consumer writes.
  A4  round trip: a point (allowed, needed, form) renders through the real
      aideep.guarantees_for to the sentence the report prints.

Pass criterion: A1, A2, A4 hold using library operations only (rank, passes,
payload_for, the constructor); A3 refused; A3s reported as it comes out.
Fallback if A1 or A2 need a bespoke branch: the DWP records the continuum as
a VOCABULARY for the docs and the guarantees line, not a mechanism, and
`--latitude` is parsed by hand like `--ai-scope` is today.

Run from anywhere:
    python tests/one-offs/thinking/deep-merge/poc_latitude_continuum.py
Reads dazzle_lib from C:/code/dazzle-lib via sys.path; imports this worktree's
aideep/airung read-only; writes nothing; no GPU, no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve()
WORKTREE = HERE.parents[4]            # tests/one-offs/thinking/deep-merge/<me>
sys.path.insert(0, str(WORKTREE))
sys.path.insert(0, "C:/code/dazzle-lib")

from dazzle_lib.continuum import Continuum, ContinuumError, ContinuumSpace  # noqa: E402

from dazzle_claude_config import aideep, airung  # noqa: E402

# -- the axes, as data ---------------------------------------------------------
WHERE = Continuum(
    name="where",
    ranks={"none": 0, "hunk": 1, "file": 2, "neighbours": 3, "project": 4},
    invariant="no edit needed",
    subtype="monopole",
)
FORM = Continuum(
    name="form",
    ranks={"no-tools": 0, "tools": 1},
    invariant="one message: the merged file and the two diffs",
    subtype="monopole",
)
FREEDOM = Continuum(
    name="freedom",
    ranks={"copy": 0, "minimal": 1, "rewrite": 2},
    invariant="every line came from one of the three sides",
    subtype="monopole",
)
SPACE = ContinuumSpace(
    name="latitude",
    axes={"where": WHERE, "form": FORM, "freedom": FREEDOM},
    presence=None,                    # a PRODUCT space: independent dimensions
    meaning="how far, and how freely, a model may change a merge",
    invariant="nothing installs without --accept",
    payloads={"form": {"no-tools": {"ceiling": "file"}, "tools": {"ceiling": "project"}}},
)


def rung_int(token: str) -> int:
    """The code's integer for a rung token; `none` is the code's 0 (no edit)."""
    return 0 if token == "none" else airung.rung_of(token)


ROWS: list[tuple[str, str, str, str]] = []   # (arm, prediction, observation, verdict)


def arm1() -> None:
    disagreements = []
    for allowed in WHERE.levels():
        for needed in WHERE.levels():
            lib_passes = WHERE.passes(needed, allowed)
            code_fails = rung_int(needed) > rung_int(allowed)     # aideep.py:326
            if lib_passes == code_fails:
                disagreements.append((allowed, needed, lib_passes, code_fails))
    obs = f"{25 - len(disagreements)} of 25 agree" + (f"; disagree: {disagreements}" if disagreements else "")
    ROWS.append(("A1 verdict gate == WHERE.passes(needed, allowed)", "25 of 25 agree", obs,
                 "survived" if not disagreements else "refuted"))


def arm2() -> None:
    disagreements = []
    for form in FORM.levels():
        ceiling = SPACE.payload_for("form", form)["ceiling"]          # data, not code
        for allowed in WHERE.levels():
            lib_ok = WHERE.passes(allowed, ceiling)
            code_refused = rung_int(allowed) >= 3 and form != "tools"  # aideep.py:255-259
            if lib_ok == code_refused:
                disagreements.append((form, allowed, lib_ok, code_refused))
    obs = f"{10 - len(disagreements)} of 10 agree" + (f"; disagree: {disagreements}" if disagreements else "")
    ROWS.append(("A2 no-tools cap == WHERE.passes(allowed, payload ceiling)", "10 of 10 agree", obs,
                 "survived" if not disagreements else "refuted"))


def arm3_control() -> bool:
    refused = not WHERE.passes("project", "file")
    companion = WHERE.passes("file", "file")
    obs = f"passes(project, file) = {not refused}; passes(file, file) = {companion}"
    ok = refused and companion
    ROWS.append(("A3 CONTROL change=project, look=file is refused", "False, and (file, file) True", obs,
                 "failed as predicted (method works)" if ok else "METHOD BROKEN"))
    return ok


def arm3_strong() -> None:
    """Does the SPACE itself refuse a cross-axis point, with no predicate of ours?"""
    findings = []
    public = [n for n in dir(SPACE) if not n.startswith("_")]
    constraint_like = [n for n in public if any(k in n.lower() for k in ("impossible", "forbid", "constrain", "refuse", "exclude"))]
    findings.append(f"constraint-shaped methods on ContinuumSpace: {constraint_like or 'none'}")
    try:
        SPACE.warmer_than("where", "file")
        findings.append("warmer_than on a product space: returned (unexpected)")
    except ContinuumError as e:
        findings.append(f"warmer_than on a product space raises: {str(e).splitlines()[0][:90]}")
    obs = "; ".join(findings)
    refuted = not constraint_like
    ROWS.append(("A3s the space itself marks the cell impossible", "refuted: no such operation; the predicate is ours",
                 obs, "refuted (as predicted)" if refuted else "survived (unexpected -- read the method)"))


def arm4() -> None:
    a = aideep.guarantees_for(rung_int("file"), rung_int("hunk"), tools=False)
    b = aideep.guarantees_for(rung_int("neighbours"), rung_int("neighbours"), tools=True)
    checks = [
        "this file only" in a, "(needed: hunk)" in a, "no tools" in a,
        "neighbouring files" in b, "(needed: neighbours)" in b, "no tools" not in b,
    ]
    obs = f"{sum(checks)} of 6 phrases present\n      no-tools/file/hunk: {a}\n      tools/neighbours/neighbours: {b}"
    ROWS.append(("A4 point -> guarantees sentence round trip", "6 of 6 phrases", obs,
                 "survived" if all(checks) else "refuted"))


def main() -> int:
    arm1()
    arm2()
    ok = arm3_control()
    arm3_strong()
    arm4()
    print("poc: the latitude axes as a dazzle-lib ContinuumSpace  (2026-09-15)\n")
    for arm, pred, obs, verdict in ROWS:
        print(f"{arm}\n  predicted: {pred}\n  observed:  {obs}\n  verdict:   {verdict}\n")
    try:
        print("space.describe():\n" + "\n".join("  " + ln for ln in SPACE.describe().splitlines()))
    except ContinuumError as e:
        print(f"space.describe() raises on a product space: {e}")
    if not ok:
        print("\nVERDICT: method-broken -- the control passed; no result is reported.")
        return 2
    weak = [r for r in ROWS if r[3] == "refuted"]
    print("\nVERDICT: " + ("survived -- A1, A2, A4 hold with library operations only; the strong claim A3s is "
                          "refuted as predicted: the space is a vocabulary and a threshold predicate, and the "
                          "cross-axis rule (change never wider than look) is ONE consumer predicate over its data."
                          if not weak else f"refuted -- {[r[0] for r in weak]}; fallback: continuum as vocabulary only."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
