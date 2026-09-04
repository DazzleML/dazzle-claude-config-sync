"""The prompt ccs builds for ``--ai``, and the check every answer must pass.

The prompt (``prompts/ai-merge.md``, package data) carries three things:
the rules the person wrote, with their ids; what ccs knows about the
history, in plain words -- evidence, never a decision; and each conflict
hunk with its lines named ``O1..``, ``B1..``, ``T1..`` and a few context
lines marked not selectable. The answer is one JSON block naming lines
per hunk, with the rules it leans on and a sentence of rationale.

Nothing is assembled until ``check_proposal`` has passed the answer. It
is mechanical -- no natural-language understanding anywhere -- and it is
where a model's drops are bounded, because a model can only address the
lines inside a hunk: every id must exist; no line text twice; each pane's
own order kept (an interleaving, never a reorder); an unselected line of
ours or theirs is fine when a selected line is a rewrite of it (the same
threshold ``merge.validate`` uses for rewrite-versus-loss) and otherwise
needs a cited rule that exists in the loaded file; a base-only line
brought back needs one too. The validator then runs on the assembled
file as the backstop. Failures carry the ``proposal:`` prefix, never the
validator's loss prefix, so the human "I dropped it on purpose" escape
can never apply to a model's drop.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path

from .aimerge import SUPERSEDE_RATIO, Hunk, select, sub_line_report
from .airules import Rules

PROPOSAL_PREFIX = "proposal:"
TEMPLATE = Path(__file__).parent / "prompts" / "ai-merge.md"

_OURS = "O (your live file)"
_BASE = "B (the common ancestor)"
_THEIRS = "T (the payload's copy)"


def _excerpt(line: str, n: int = 60) -> str:
    return line if len(line) <= n else line[:n - 3] + "..."


# -- rendering -----------------------------------------------------------------

def render_rules(rules: Rules) -> str:
    """The rules block: the describe line, then ``R1: text`` per rule --
    or, with no file, the sentence that says nothing can license a drop."""
    if rules.source == "none":
        return (f"{rules.describe()}\n\nNo rules file: every line you leave out that "
                f"is not a rewrite of a line you keep must stay, because nothing "
                f"licenses a drop.")
    out = [rules.describe(), ""]
    for rid, text in rules.ids.items():
        body = text.replace("\n", "\n    ")
        out.append(f"{rid}: {body}")
    return "\n".join(out)


def _pane(title: str, prefix: str, lines: list[str], empty: str) -> list[str]:
    if not lines:
        return [f"{title}: ({empty})"]
    out = [f"{title}:"]
    out += [f"{prefix}{k}: {line}" for k, line in enumerate(lines, 1)]
    return out


def render_hunks(hunks: list[Hunk]) -> str:
    """Every hunk: a heading with its kind, the marked context, the three
    panes with ids, and -- for a paragraph hunk -- the sub-line report."""
    blocks: list[str] = []
    for h in hunks:
        out = [f"### Hunk {h.n} ({h.kind})"]
        if h.before:
            out.append("context (not selectable):")
            out += [f"    | {l}" for l in h.before]
        out += _pane(_OURS, "O", h.ours, "empty -- nothing here in your live file")
        out += _pane(_BASE, "B", h.base, "empty -- nothing here in the common ancestor")
        out += _pane(_THEIRS, "T", h.theirs, "empty -- nothing here in the payload's copy")
        if h.after:
            out.append("context (not selectable):")
            out += [f"    | {l}" for l in h.after]
        report = sub_line_report(h)
        if report:
            out.append("")
            out += report
        blocks.append("\n".join(out))
    return "\n\n".join(blocks)


def build_prompt(label: str, hunks: list[Hunk], rules: Rules, dossier: str) -> str:
    """The prompt for one file, from the template."""
    template = TEMPLATE.read_text(encoding="utf-8")
    return template.format(
        label=label,
        rules=render_rules(rules),
        dossier=dossier.strip() or "(no ancestry evidence beyond the base ccs chose)",
        hunks=render_hunks(hunks),
    )


# -- the answer ----------------------------------------------------------------

@dataclass
class Choice:
    """One hunk's answer: the ids in order, the rules cited, the reason."""
    hunk: int
    lines: list[str]
    rules: list[str] = field(default_factory=list)
    rationale: str = ""


def parse_response(data) -> tuple[dict[int, Choice], list[str]]:
    """The documented shape, strictly: ``{"hunks": [{"hunk": n, "lines":
    [...], "rules": [...], "rationale": "..."}]}``. Anything else is a
    failure naming what was wrong, never a guess."""
    failures: list[str] = []
    choices: dict[int, Choice] = {}
    if not isinstance(data, dict) or not isinstance(data.get("hunks"), list):
        return {}, [f"{PROPOSAL_PREFIX} the answer is not an object with a \"hunks\" list"]
    for k, item in enumerate(data["hunks"], 1):
        if not isinstance(item, dict):
            failures.append(f"{PROPOSAL_PREFIX} answer {k} is not an object")
            continue
        n = item.get("hunk")
        lines = item.get("lines")
        rules = item.get("rules", [])
        rationale = item.get("rationale", "")
        if not isinstance(n, int) or isinstance(n, bool):
            failures.append(f"{PROPOSAL_PREFIX} answer {k} has no integer \"hunk\"")
            continue
        if not isinstance(lines, list) or not all(isinstance(x, str) for x in lines):
            failures.append(f"{PROPOSAL_PREFIX} hunk {n}: \"lines\" is not a list of ids")
            continue
        if not isinstance(rules, list) or not all(isinstance(x, str) for x in rules):
            failures.append(f"{PROPOSAL_PREFIX} hunk {n}: \"rules\" is not a list of ids")
            continue
        if not isinstance(rationale, str):
            rationale = str(rationale)
        if n in choices:
            failures.append(f"{PROPOSAL_PREFIX} hunk {n} is answered twice")
            continue
        choices[n] = Choice(n, list(lines), list(rules), rationale)
    return choices, failures


# -- the check -----------------------------------------------------------------

def _superseded(text: str, selected: set[str]) -> bool:
    return any(difflib.SequenceMatcher(None, text, s).ratio() >= SUPERSEDE_RATIO
               for s in selected)


def check_proposal(hunks: list[Hunk], choices: dict[int, Choice], rules: Rules) -> list[str]:
    """Every failure in the answer, or an empty list. See the module
    docstring for the five rules; each failure names the hunk and the id."""
    failures: list[str] = []
    by_n = {h.n: h for h in hunks}
    for n in sorted(choices):
        if n not in by_n:
            failures.append(f"{PROPOSAL_PREFIX} hunk {n}: no such hunk")
    for h in hunks:
        c = choices.get(h.n)
        if c is None:
            failures.append(f"{PROPOSAL_PREFIX} hunk {h.n}: no resolution given")
            continue
        table = h.ids()
        # cited rules must exist in the loaded file
        missing = [r for r in c.rules if r not in rules.ids]
        for r in missing:
            failures.append(f"{PROPOSAL_PREFIX} hunk {h.n}: cites rule {r}, which is not in "
                            f"the loaded rules ({rules.path or 'no rules file'})")
        licensed = bool(c.rules) and not missing
        # (i) every id exists
        unknown = [i for i in c.lines if i not in table]
        if unknown:
            failures.append(f"{PROPOSAL_PREFIX} hunk {h.n}: names {', '.join(unknown)}, "
                            f"not in its panes")
            continue
        selected_lines = [table[i] for i in c.lines]
        # (ii) no line text twice
        seen: set[str] = set()
        for t in selected_lines:
            s = t.strip()
            if s and s in seen:
                failures.append(f"{PROPOSAL_PREFIX} hunk {h.n}: {_excerpt(s)!r} is selected twice")
                break
            seen.add(s)
        # (iii) each pane's own order is kept
        for prefix in ("O", "B", "T"):
            ids = [i for i in c.lines if i[0] == prefix]
            idx = [int(i[1:]) for i in ids]
            if any(b <= a for a, b in zip(idx, idx[1:])):
                failures.append(f"{PROPOSAL_PREFIX} hunk {h.n}: {prefix} lines out of their "
                                f"pane's order ({', '.join(ids)}) -- interleave, never reorder")
        # (iv) an unselected O/T line is superseded or licensed
        selected = {t.strip() for t in selected_lines if t.strip()}
        for prefix, pane in (("O", h.ours), ("T", h.theirs)):
            for k, line in enumerate(pane, 1):
                s = line.strip()
                if not s or s in selected or _superseded(s, selected):
                    continue
                if licensed:
                    continue
                failures.append(f"{PROPOSAL_PREFIX} hunk {h.n}: {prefix}{k} dropped with no "
                                f"rule cited ({_excerpt(s)!r})")
        # (v) base-only text brought back needs a rule
        present = {l.strip() for l in h.ours + h.theirs if l.strip()}
        for i in c.lines:
            s = table[i].strip()
            if i[0] == "B" and s and s not in present and not licensed:
                failures.append(f"{PROPOSAL_PREFIX} hunk {h.n}: {i} brings back base-only "
                                f"text with no rule cited ({_excerpt(s)!r})")
    return failures


def resolve(hunks: list[Hunk], choices: dict[int, Choice]) -> dict[int, list[str]]:
    """The chosen lines per hunk, for ``aimerge.assemble``. Only after
    ``check_proposal`` returned nothing."""
    return {h.n: select(h, choices[h.n].lines) for h in hunks}
