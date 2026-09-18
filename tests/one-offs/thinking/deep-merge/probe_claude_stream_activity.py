"""Is a thinking model observably alive? One call to Claude Code's streaming
output, timed as it arrives.

Why (2026-09-18): the deep step on Opus timed out at the fixed 120 s on the
real paragraph case. Claude Code's own transcript of the run showed it alive
the whole time -- five tool calls, and 77 s of thinking with no output. The
maintainer's proposal: no wall clock by default; let a run continue while it
is doing something, and declare it dead only when nothing is observable for a
while. That design stands or falls on one fact: does thinking show up as
output while it happens? With `--output-format text` it does not (the answer
prints at the end). With `--output-format stream-json --verbose
--include-partial-messages` Claude Code may emit content-block deltas as
they arrive, thinking included. This probe finds out.

What it does: runs `claude -p - --output-format stream-json --verbose
--include-partial-messages --model <model>` with a prompt that asks for
careful thought first, reads stdout line by line as it arrives, prints each
event's arrival time and kind, and summarises: the longest gap between two
events, and whether any `thinking_delta` arrived during that gap. One call,
the maintainer's money; nothing else is touched.

Usage: python probe_claude_stream_activity.py [--model claude-opus-5]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

PROMPT = (
    "Before answering, think carefully and at length about the following, "
    "weighing at least three distinct explanations against each other: why "
    "does a three-way merge of two rewrites of the same paragraph lose "
    "information whichever side is taken whole? Then answer in two sentences.\n"
)


def kind_of(event: dict) -> str:
    t = event.get("type") or "?"
    inner = event.get("event") or {}
    it = inner.get("type") or ""
    delta = inner.get("delta") or {}
    dt = delta.get("type") or ""
    block = (inner.get("content_block") or {}).get("type") or ""
    parts = [t]
    if it:
        parts.append(it)
    if block:
        parts.append("block=" + block)
    if dt:
        parts.append("delta=" + dt)
    return " ".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default="claude-opus-5")
    ap.add_argument("--exe", default="claude")
    args = ap.parse_args(argv)

    cmd = [args.exe, "-p", "-", "--output-format", "stream-json", "--verbose",
           "--include-partial-messages", "--model", args.model]
    print("running:", " ".join(cmd))
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8",
                            errors="replace")
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(PROMPT)
    proc.stdin.close()

    events: list[tuple[float, str]] = []
    thinking_deltas = 0
    text_deltas = 0
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        at = time.monotonic() - t0
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            events.append((at, "unparsed: " + line[:60]))
            print(f"{at:7.2f}s  unparsed: {line[:80]}")
            continue
        k = kind_of(ev)
        if "thinking_delta" in k:
            thinking_deltas += 1
        if "text_delta" in k:
            text_deltas += 1
        events.append((at, k))
        print(f"{at:7.2f}s  {k}")
    rc = proc.wait()
    err = proc.stderr.read() if proc.stderr else ""
    total = time.monotonic() - t0

    print()
    print(f"exit {rc}; {len(events)} events in {total:.1f}s; "
          f"thinking deltas {thinking_deltas}; text deltas {text_deltas}")
    if len(events) >= 2:
        gaps = [(events[i][0] - events[i - 1][0], events[i - 1][1], events[i][1])
                for i in range(1, len(events))]
        g, before, after = max(gaps, key=lambda x: x[0])
        print(f"longest silence {g:.1f}s, between '{before}' and '{after}'")
    if thinking_deltas:
        print("thinking deltas during the run: yes -- a thinking model is "
              "observably alive through this output format")
    else:
        print("thinking deltas during the run: no -- either the model did not "
              "think, or thinking is invisible here; an idle detector would "
              "have to look elsewhere (the transcript file's growth, or a "
              "threshold above the longest plausible thought)")
    if err.strip():
        print("stderr:", err.strip()[:400])
    return 0


if __name__ == "__main__":
    sys.exit(main())
