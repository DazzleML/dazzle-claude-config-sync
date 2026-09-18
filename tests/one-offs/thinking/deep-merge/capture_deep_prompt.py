"""Capture the exact prompt the deep step sends, without asking any model.

Runs the real command -- `ccs merge <file> --ai lmstudio,deep --ai-scope <scope>
--no-launch` -- against a scratch world built by build_deep_world.py, with the
server transport replaced by a fake that writes the request's prompt to a file
and answers "failed". The run prints `NOT KEPT ... captured: ...`; nothing is
sent anywhere, no model is loaded.

Why: on 2026-09-16 the first live deep run on LM Studio produced ~33 tokens in
107 s. LM Studio's log truncates the request body, so this writes the prompt
out byte-for-byte for pasting into LM Studio's own chat -- the same model, the
same text, through a different path -- to see whether the slowness is the
model or the API path.

Usage:
    python tests/one-offs/thinking/deep-merge/capture_deep_prompt.py <world> [--file skills/s.py]
                                                                     [--scope hunk] [--out PATH]
The prompt lands at <world>/deep-prompt.txt unless --out says otherwise.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dazzle_claude_config._vendor.ailib import backend as _bm
from dazzle_claude_config._vendor.ailib.types import Readiness, Response
from dazzle_claude_config.cli import main


class _Capture:
    """A fake `openai_compat` transport: ready, no tools, writes the prompt."""
    out: str = ""

    def probe(self, spec):
        return Readiness(True, "captured -- no server was asked", warning="")

    def capabilities(self, spec):
        return frozenset({"model", "schema"})

    def invoke(self, spec, req):
        Path(_Capture.out).write_text(req.prompt, encoding="utf-8", newline="\n")
        n = len(req.prompt)
        return Response("failed", error=f"captured: the prompt is at {_Capture.out} "
                                        f"({n:,} chars, roughly {n // 4:,} tokens); nothing was sent")


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("world", help="the scratch world from build_deep_world.py")
    ap.add_argument("--file", default="skills/s.py", help="the payload file's label (default skills/s.py)")
    ap.add_argument("--scope", default="hunk", choices=("hunk", "file"))
    ap.add_argument("--out", default=None, help="where to write the prompt (default <world>/deep-prompt.txt)")
    a = ap.parse_args(argv)
    w = Path(a.world).expanduser()
    if not (w / "checkout").is_dir():
        print(f"{w} is not a world built by build_deep_world.py (no checkout/)")
        return 2
    out = Path(a.out).expanduser() if a.out else w / "deep-prompt.txt"
    _bm.transport_for("openai_compat")                 # populate the registry, then replace the entry
    _bm._TRANSPORTS["openai_compat"] = _Capture()
    _Capture.out = str(out)
    main(["--checkout-dir", str(w / "checkout"), "--claude-dir", str(w / "live"),
          "--user-claude", str(w / "user"), "--no-fetch", "--no-color",
          "merge", a.file, "--ai", "lmstudio,deep", "--ai-scope", a.scope, "--no-launch"])
    if out.is_file():
        print(f"\nprompt written: {out}  ({out.stat().st_size:,} bytes)")
        return 0
    print("\nno prompt was captured -- the deep step did not reach the transport (read the report above)")
    return 1


if __name__ == "__main__":
    sys.exit(run())
