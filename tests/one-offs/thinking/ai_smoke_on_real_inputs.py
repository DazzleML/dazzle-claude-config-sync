"""Smoke: the AI step on a COPY of one real merge input set, prompt-only.

Never touches the real workspace (~/claude/merge/ccs): the three inputs are
copied to a scratch directory and everything the step writes lands there.
Prints only what the step reports -- the sub-line report, the prompt's
size and its section headings -- not the configuration text itself.

    python tests/one-offs/thinking/ai_smoke_on_real_inputs.py [label]

Default label: skills/think/SKILL.md (the one dual-touched file measured in
the 2026-09-03 consultation, M6).
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from dazzle_claude_config import aistep, airecord  # noqa: E402

label = sys.argv[1] if len(sys.argv) > 1 else "skills/think/SKILL.md"
safe = label.replace("/", "__")
real = Path.home() / "claude" / "merge" / "ccs" / f"{safe}.merged.inputs"
if not real.is_dir():
    print(f"no real inputs at {real}; nothing to smoke")
    sys.exit(0)

scratch = Path(tempfile.mkdtemp(prefix="ccs-ai-smoke-"))
for name in ("ours", "base", "theirs"):
    shutil.copy2(real / name, scratch / name)
ws = scratch / "ws"
ws.mkdir()
opts = aistep.AiOptions(rules_dir=scratch / "rules", prompts_dir=scratch / "prompts",
                        cache_dir=scratch / "cache")
out = aistep.ai_step(label=label, ours=scratch / "ours", base=scratch / "base",
                     theirs=scratch / "theirs", merged=ws / f"{safe}.merged",
                     opts=opts, workdir=scratch / "work")
print(f"status: {out.status}; hunks: {out.hunks}; {out.rules}")
for line in out.reports:
    print(line)
if out.prompt_path:
    text = out.prompt_path.read_text(encoding="utf-8")
    print(f"prompt: {len(text)} chars, {text.count(chr(10))} lines, at {out.prompt_path}")
    for l in text.splitlines():
        if l.startswith("#") or l.startswith("### Hunk"):
            print("  " + l)
    print(f"answer goes to: {out.response_path}")
print(f"scratch left for inspection: {scratch}")
