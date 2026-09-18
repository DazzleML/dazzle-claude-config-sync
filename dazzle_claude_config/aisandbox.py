"""The disposable copy the deep step works in, and the guard over the real trees.

The deep merge (#64) lets a model with tools read and WRITE -- but only in
a copy it can be handed, never in the checkout or the live tree. This module
makes that copy, measures what changed in it, and proves the real trees did
not move.

    ws/<safe>.ai-deep/                 the sandbox root: the child's cwd
        checkout/                      a detached git worktree of the checkout
                                       (the same files, at HEAD; a copy when
                                       the checkout is not a repository)
        live/<entry.target>/           a copy of the live component
        checkout/<entry.repo>/<rel>    the payload file, OVERWRITTEN with the
                                       mechanical result -- what the model
                                       reads for meaning

Two layers of containment, both measured before this was built (2026-09-09):
the CLI's own flag (claude's `--allowedTools`, codex's `-s workspace-write`
write only inside their cwd) is layer one and belongs to the transport; this
module is layer two -- a hash of every real file before the call and after
it, so a backend that reached outside is CAUGHT and its answer discarded.
`git worktree` is used for the checkout because it is the cheapest faithful
copy and git removes it cleanly; on Windows a child's open handle can block
that removal, so `release` retries and prunes.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

SANDBOX_SUFFIX = ".ai-deep"
CHECKOUT_DIR = "checkout"
LIVE_DIR = "live"


@dataclass
class Sandbox:
    root: Path                  # the child's cwd
    checkout: Path              # root/checkout
    live: Path | None           # root/live/<target>, when the entry has a live component
    payload_file: Path          # root/checkout/<entry.repo>/<rel>, holding the mechanical result
    payload_rel: str            # the same, relative to root, posix
    source_repo: Path           # the real checkout the worktree hangs off
    worktree: bool              # True: checkout/ is a git worktree; False: a plain copy
    note: str = ""              # why a copy, when it is one


@dataclass
class Guard:
    """A hash of every file under each real root, taken before the call;
    `escapes()` names what changed since."""
    roots: list[Path]
    before: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def take(cls, roots) -> "Guard":
        g = cls([Path(r) for r in roots if r is not None and Path(r).exists()])
        g.before = {str(r): digest(r) for r in g.roots}
        return g

    def escapes(self) -> list[str]:
        out: list[str] = []
        for r in self.roots:
            for rel in changed(self.before[str(r)], digest(r)):
                out.append(f"{r.as_posix()}/{rel}")
        return out


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def digest(root: Path) -> dict[str, str]:
    """sha256 per file under `root`, keyed by posix path relative to it.
    Anything named `.git` (a worktree's pointer FILE, a repository's
    directory) is not the tree's content and is skipped."""
    out: dict[str, str] = {}
    root = Path(root)
    if root.is_file():
        return {root.name: hashlib.sha256(root.read_bytes()).hexdigest()}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        for name in sorted(filenames):
            if name == ".git":
                continue
            p = Path(dirpath) / name
            try:
                out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
            except OSError:
                out[p.relative_to(root).as_posix()] = "?unreadable"
    return out


def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Paths added, removed or modified between two digests, sorted."""
    return sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))


def _remove_tree(path: Path) -> None:
    for attempt in range(3):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        time.sleep(0.2 * (attempt + 1))          # a child's handle on Windows


def _remove_worktree(source_repo: Path, checkout: Path) -> None:
    if not checkout.exists():
        _git(source_repo, "worktree", "prune")
        return
    r = _git(source_repo, "worktree", "remove", "--force", str(checkout))
    if r.returncode != 0:
        time.sleep(0.3)
        _git(source_repo, "worktree", "prune")
        r = _git(source_repo, "worktree", "remove", "--force", str(checkout))
    if checkout.exists():
        _remove_tree(checkout)
        _git(source_repo, "worktree", "prune")


def release_root(root: Path, source_repo: Path | None) -> None:
    """Remove a sandbox root whatever state it is in (a stale one from an
    interrupted run included): the worktree first, through git, then the
    rest of the directory."""
    root = Path(root)
    if not root.exists():
        return
    co = root / CHECKOUT_DIR
    if source_repo is not None and (co / ".git").exists():
        _remove_worktree(Path(source_repo), co)
    _remove_tree(root)


def prepare(*, workdir: Path, checkout_repo: Path, live_root: Path | None, entry, rel: str,
            mechanical: bytes) -> Sandbox:
    """Make the sandbox at `workdir`: the checkout as a worktree (a copy
    when `git worktree add` refuses -- an un-initialised checkout, say),
    the live component copied beside it, the mechanical result written
    over the payload file. A leftover from an interrupted run is removed
    first. Nothing under `checkout_repo` or `live_root` is written."""
    root = Path(workdir)
    checkout_repo = Path(checkout_repo)
    release_root(root, checkout_repo)
    root.mkdir(parents=True, exist_ok=True)
    co = root / CHECKOUT_DIR
    worktree, note = False, ""
    # Only a directory that IS a repository gets a worktree. Without this
    # gate git searches upward from the checkout and would happily make a
    # worktree of whatever repository contains it -- measured on the first
    # copy-mode test: a plain directory under the temp tree resolved to the
    # HOME repository, and the sandbox became a checkout of ~/.claude.
    r = None
    if (checkout_repo / ".git").exists():
        r = _git(checkout_repo, "worktree", "add", "--detach", "-q", str(co), "HEAD")
    if r is not None and r.returncode == 0 and (co / ".git").exists():
        worktree = True
    else:
        if co.exists():
            _remove_tree(co)
        shutil.copytree(checkout_repo, co, ignore=shutil.ignore_patterns(".git"))
        why = r.stderr.strip().splitlines()[-1][:120] if (r is not None and r.stderr.strip()) else "not a repository"
        note = f"the checkout is a plain copy, not a worktree ({why})"
    live: Path | None = None
    target = getattr(entry, "target", None)
    if live_root is not None and target:
        src = Path(live_root) / target
        dst = root / LIVE_DIR / target
        if src.is_dir():
            shutil.copytree(src, dst)
            live = dst
        elif src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            live = dst
    repo_rel = f"{entry.repo}/{rel}" if rel else entry.repo
    payload_rel = f"{CHECKOUT_DIR}/{repo_rel}"
    payload_file = root / Path(payload_rel)
    payload_file.parent.mkdir(parents=True, exist_ok=True)
    payload_file.write_bytes(mechanical)
    return Sandbox(root=root, checkout=co, live=live, payload_file=payload_file, payload_rel=payload_rel,
                   source_repo=checkout_repo, worktree=worktree, note=note)


def release(sb: Sandbox) -> None:
    """Remove the sandbox: the worktree through git, then the directory."""
    if sb.worktree:
        _remove_worktree(sb.source_repo, sb.checkout)
    _remove_tree(sb.root)


def before_content(sb: Sandbox, rel: str, live_root: Path | None) -> bytes:
    """What a sandbox path held BEFORE the call, without a copy of every
    file: a checkout path from the worktree's HEAD, a live path from the
    real live tree (the guard proves it did not move); "" for a file that
    did not exist."""
    parts = rel.split("/", 1)
    if parts[0] == CHECKOUT_DIR and len(parts) == 2:
        if sb.worktree:
            r = subprocess.run(["git", "-C", str(sb.checkout), "show", f"HEAD:{parts[1]}", "--"],
                               capture_output=True)
            return r.stdout if r.returncode == 0 else b""
        p = sb.source_repo / parts[1]
        return p.read_bytes() if p.is_file() else b""
    if parts[0] == LIVE_DIR and len(parts) == 2 and live_root is not None:
        p = Path(live_root) / parts[1]
        return p.read_bytes() if p.is_file() else b""
    return b""
