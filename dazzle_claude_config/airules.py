"""The rules a person wrote for ``ccs merge --ai``, loaded and named.

Rules are the person's policy in their own words -- plain prose, in user
territory, versioned wherever they like. One file per path, named the way
everything else ccs writes about a file is named: the label flattened, then
what the file is for. ``dotclaude/CLAUDE.md`` reads
``~/claude/ccs-merge-rules/dotclaude__CLAUDE.md.rules.md``, beside the
``_prompts/dotclaude__CLAUDE.md-<ts>.md`` the step writes and the
``dotclaude__CLAUDE.md.merged`` in the workspace. Else ``_default.md``,
else none.

The shape first built was ``<label>.md``, which put the file at
``dotclaude/CLAUDE.md.md`` -- a directory to create AND a doubled extension
that reads as a typo. Two readers called it a bug within a day of seeing
it, which is the right verdict for a path a person is meant to create by
hand. ``.rules.md`` says what the file is, keeps the label recognisable,
needs no directory, and keeps every rules file a ``.md`` an editor will
highlight.

"None" is a named degradation the output says out loud; it is never a crash
and never a silent default. Rules decide HOW a file's dual-touched hunks
resolve; the manifest still decides WHETHER a file is merged at all.

Every non-blank paragraph gets a positional id (``R1``, ``R2``, ...). The
prompt shows the ids; a model cites one when it drops a line; ccs checks
the citation mechanically -- the id exists in the file whose hash the
output prints beside every citation. No natural-language understanding
anywhere in the check, which is the point. Positional ids are stable only
while the file is not reordered, and the hash beside them is what says
whether it was.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_NAME = "_default.md"
PROMPTS_NAME = "_prompts"
RULES_SUFFIX = ".rules.md"      # <flattened label> + this; see the module docstring


@dataclass
class Rules:
    source: str                 # "path" | "default" | "none"
    path: Path | None
    sha: str                    # sha256 of the LF-normalised bytes; "" when none
    ids: dict[str, str]         # "R1" -> the paragraph, in file order
    text: str = ""
    looked: tuple[Path, ...] = ()   # where load_rules looked, for the "none" line

    def describe(self) -> str:
        """One line for the report and the prompt: which file, which hash."""
        if self.source == "none":
            where = " or ".join(str(p) for p in self.looked)
            return f"rules: none (no file at {where})"
        n = len(self.ids)
        return f"rules: {self.path} @ {self.sha[:7]} ({n} rule{'s' if n != 1 else ''})"


def rules_dir(user_claude: Path) -> Path:
    """`~/claude/ccs-merge-rules` -- user territory, never the payload."""
    return Path(user_claude) / "ccs-merge-rules"


def prompts_dir(user_claude: Path) -> Path:
    """Where ``--ai prompt-only`` writes the prompt a person carries elsewhere."""
    return rules_dir(user_claude) / PROMPTS_NAME


def safe_name(label: str) -> str:
    """The workspace's own transform: one flat file name per label, however
    deep the label. Shared with the merge workspace and the prompt directory
    so a person sees one naming rule across all three, not three."""
    return label.replace("/", "__").replace("\\", "__")


def candidates(label: str, rules_dir: Path) -> list[Path]:
    """The per-path file, then the default -- the order load_rules tries."""
    return [Path(rules_dir) / (safe_name(label) + RULES_SUFFIX),
            Path(rules_dir) / DEFAULT_NAME]


_PARAGRAPH_BREAK = re.compile(r"(?:\r?\n)[ \t]*(?:\r?\n)+")


def split_rules(text: str) -> dict[str, str]:
    """Paragraphs to ids. A paragraph made only of ``#`` lines is a heading
    (structure, not policy) and takes no id, so numbering follows the rules
    a person would count. Blank paragraphs at either end take none either;
    every line keeps its own indentation and loses only trailing blanks."""
    out: dict[str, str] = {}
    k = 0
    for para in _PARAGRAPH_BREAK.split(text):
        lines = [l.rstrip() for l in para.splitlines() if l.strip()]
        if not lines or all(l.lstrip().startswith("#") for l in lines):
            continue
        k += 1
        out[f"R{k}"] = "\n".join(lines)
    return out


def load_rules(label: str, rules_dir: Path) -> Rules:
    """The rules for `label`: the per-path file, else the default, else a
    Rules with source ``none`` that names both places it looked."""
    cands = candidates(label, rules_dir)
    for p, source in zip(cands, ("path", "default")):
        if p.is_file():
            raw = p.read_bytes()
            text = raw.decode("utf-8-sig", errors="replace")
            sha = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
            return Rules(source, p, sha, split_rules(text), text, tuple(cands))
    return Rules("none", None, "", {}, "", tuple(cands))
