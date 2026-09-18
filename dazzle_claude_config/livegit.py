"""A read-only look at the live tree's own git history (issue #40, the
minimal form).

The live tree -- ``~/.claude``, ``~/claude/claude-config`` -- may sit inside
a git repository of the person's own. On plzwork it does: ``~/.claude``
resolves to the HOME repository, the one ``gitops.py`` is built to refuse
(measured 2026-09-03, the consultation's M4). That is why this module is
not in ``gitops.py``: that module's whole invariant is that it cannot touch
the home repo, and a probe that reads it must live where the invariant is
"reads only", enforced twice -- by construction (the verbs below are the
only ones this module knows) and by a test that hashes a repository's HEAD,
index and status before and after a probe.

What it answers, per path, at ~40 ms: is there a repository; is the file
tracked in it; the last few commits that touched it. Evidence for the
dossier -- "your live edit has its own history and this is it" -- never a
decision, and never a base: ccs chooses the base from the checkout.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

#: The only git verbs this module runs. A test asserts it.
READ_VERBS = ("rev-parse", "ls-files", "log")


@dataclass
class LiveGit:
    toplevel: Path | None          # the repository the path sits in, or None
    tracked: bool                  # the path is tracked there
    recent: list[tuple[str, str]]  # (short sha, YYYY-MM-DD), newest first


def _run(args: list[str], cwd: Path) -> tuple[int, str]:
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, p.stdout


def _iso_date(unix_ts: str) -> str:
    import datetime as _dt
    try:
        return _dt.datetime.fromtimestamp(int(unix_ts)).date().isoformat()
    except (ValueError, OverflowError, OSError):
        return ""


def probe(path: Path, limit: int = 5) -> LiveGit:
    """What the live tree's git says about `path`. Reads only."""
    path = Path(path)
    cwd = path.parent if not path.is_dir() else path
    if not cwd.is_dir():
        return LiveGit(None, False, [])
    rc, out = _run(["rev-parse", "--show-toplevel"], cwd)
    if rc != 0 or not out.strip():
        return LiveGit(None, False, [])
    top = Path(out.strip()).resolve()
    rc, _ = _run(["ls-files", "--error-unmatch", "--", str(path)], cwd)
    if rc != 0:
        return LiveGit(top, False, [])
    rc, log = _run(["log", "-n", str(limit), "--format=%h %ct", "--", str(path)], cwd)
    recent: list[tuple[str, str]] = []
    if rc == 0:
        for line in log.splitlines():
            parts = line.split()
            if len(parts) == 2:
                recent.append((parts[0], _iso_date(parts[1])))
    return LiveGit(top, True, recent)


def describe(lg: LiveGit) -> str:
    """One sentence for the dossier."""
    if lg.toplevel is None:
        return "Your live file is not tracked by any git repository."
    if not lg.tracked:
        return (f"Your live tree is a git repository ({lg.toplevel}), but this file is "
                f"not tracked there.")
    if not lg.recent:
        return (f"Your live tree is a git repository ({lg.toplevel}); this file is tracked "
                f"there but has no commits yet.")
    shown = ", ".join(f"{sha} {date}" for sha, date in lg.recent)
    return (f"Your live tree is a git repository ({lg.toplevel}); this file's recent "
            f"commits there, newest first: {shown}.")
