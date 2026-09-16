"""A real deep run whose raw reply is kept.

Runs the real command -- `ccs merge <file> --ai lmstudio,deep --ai-scope <scope>
--no-launch` -- against a scratch world from build_deep_world.py, with the
server transport WRAPPED, not replaced: every call goes to the real transport
and the real server, and the reply's text (or the failure sentence) is also
written to a file. Nothing else changes.

Why (2026-09-16): the first real run at a right-sized context window came
back in 7 s and was refused as `corrupt patch at line 13`; the deep step
releases its sandbox afterwards and keeps no copy of the reply, so what the
model actually wrote could not be read. The recipe keeps its reply beside the
proposal (`.merged-ai.response.json`); the deep step should too -- until it
does, this is the door.

Usage:
    python tests/one-offs/thinking/deep-merge/tee_deep_run.py <world> [--file skills/s.py]
                                                                [--scope hunk] [--out PATH]
The reply lands at <world>/deep-reply.txt unless --out says otherwise.
This DOES call the model named by the lmstudio preset; the model must already be loaded.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from dazzle_claude_config._vendor.ailib import backend as _bm
from dazzle_claude_config.cli import main


class _Tee:
    """Wraps the real transport; writes what came back."""
    out: str = ""

    def __init__(self, real):
        self._real = real

    def probe(self, spec):
        return self._real.probe(spec)

    def capabilities(self, spec):
        return self._real.capabilities(spec)

    def invoke(self, spec, req):
        started = time.monotonic()
        resp = self._real.invoke(spec, req)
        elapsed = time.monotonic() - started
        text = resp.text if resp.ok else f"[{resp.status}] {resp.error}"
        Path(_Tee.out).write_text(text, encoding="utf-8", newline="\n")
        print(f"[tee] {resp.status} from {resp.model_used or '?'} in {elapsed:.1f}s; "
              f"{len(text):,} chars written to {_Tee.out}")
        return resp

    def __getattr__(self, name):                       # anything else the step asks of a transport
        return getattr(self._real, name)


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("world", help="the scratch world from build_deep_world.py")
    ap.add_argument("--file", default="skills/s.py", help="the payload file's label (default skills/s.py)")
    ap.add_argument("--scope", default="hunk", choices=("hunk", "file"))
    ap.add_argument("--out", default=None, help="where to write the reply (default <world>/deep-reply.txt)")
    a = ap.parse_args(argv)
    w = Path(a.world).expanduser()
    if not (w / "checkout").is_dir():
        print(f"{w} is not a world built by build_deep_world.py (no checkout/)")
        return 2
    _Tee.out = str(Path(a.out).expanduser() if a.out else w / "deep-reply.txt")
    real = _bm.transport_for("openai_compat")
    _bm._TRANSPORTS["openai_compat"] = _Tee(real)
    return main(["--checkout-dir", str(w / "checkout"), "--claude-dir", str(w / "live"),
                 "--user-claude", str(w / "user"), "--no-fetch", "--no-color",
                 "merge", a.file, "--ai", "lmstudio,deep", "--ai-scope", a.scope, "--no-launch"])


if __name__ == "__main__":
    sys.exit(run())
