"""Replay a model's reply through the deep step's real pipeline, without a model.

`--ai-response` carries an answer back for the RECIPE only (aistep.py); the
deep step has no such door yet. This one-off opens one for a probe: it runs
the real command -- `ccs merge <file> --ai lmstudio,deep --ai-scope <scope>
--no-launch` -- against a scratch world from build_deep_world.py, with the
server transport replaced by a fake that answers with the text of a file.
Everything after the transport is real: the fenced-diff capture, `git apply`,
the rung classifier's verdict, the record, the report.

The file may be the raw reply, or an LM Studio chat export (.md): when it
contains a `### Assistant` heading, everything after the LAST one is the
reply -- thinking included, which is the point: the parsers are then judged
against a reply as messy as a real one.

Why (2026-09-16): the maintainer pasted the captured deep prompt into LM
Studio's chat; the model's final answer was the golden fix as a zero-context
hunk, which `git apply` refuses without `--unidiff-zero`. Replaying that reply
shows the refusal through the command; after the apply call is hardened, the
same replay should stage `.merged-ai.1`.

Usage:
    python tests/one-offs/thinking/deep-merge/replay_deep_answer.py <world> <reply-file>
                                                                    [--file skills/s.py] [--scope hunk]
Nothing is sent anywhere; no model is loaded.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dazzle_claude_config._vendor.ailib import backend as _bm
from dazzle_claude_config._vendor.ailib.types import Readiness, Response
from dazzle_claude_config.cli import main


def reply_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig")
    marker = "### Assistant"
    if marker in text:
        text = text[text.rindex(marker) + len(marker):]
    return text.strip() + "\n"


class _Replay:
    """A fake `openai_compat` transport: ready, no tools, answers with the file."""
    text: str = ""

    def probe(self, spec):
        return Readiness(True, "replay -- no server was asked", warning="")

    def capabilities(self, spec):
        return frozenset({"model", "schema"})

    def invoke(self, spec, req):
        return Response("answered", text=_Replay.text, model_used="replayed-reply", honoured=("model",))


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("world", help="the scratch world from build_deep_world.py")
    ap.add_argument("reply", help="the model's reply: raw text, or an LM Studio chat export (.md)")
    ap.add_argument("--file", default="skills/s.py", help="the payload file's label (default skills/s.py)")
    ap.add_argument("--scope", default="hunk", choices=("hunk", "file"))
    a = ap.parse_args(argv)
    w = Path(a.world).expanduser()
    if not (w / "checkout").is_dir():
        print(f"{w} is not a world built by build_deep_world.py (no checkout/)")
        return 2
    _Replay.text = reply_text(Path(a.reply).expanduser())
    print(f"replaying {len(_Replay.text):,} chars of reply from {a.reply}\n")
    _bm.transport_for("openai_compat")
    _bm._TRANSPORTS["openai_compat"] = _Replay()
    return main(["--checkout-dir", str(w / "checkout"), "--claude-dir", str(w / "live"),
                 "--user-claude", str(w / "user"), "--no-fetch", "--no-color",
                 "merge", a.file, "--ai", "lmstudio,deep", "--ai-scope", a.scope, "--no-launch"])


if __name__ == "__main__":
    sys.exit(run())
