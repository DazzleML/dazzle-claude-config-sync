# `ccs merge --ai`: a proposal beside your file

A three-way merge leaves you the hunks both sides changed. `--ai` asks a model to resolve exactly those hunks, under rules you wrote, and puts its answer in a second file beside yours. It installs nothing. You look, you edit or you don't, and `--accept` installs your file, as it always has.

```
ccs merge skills/think/SKILL.md --ai                 # prompt-only unless ai_merge_backend says otherwise
ccs merge skills/think/SKILL.md --ai claude          # the Claude Code CLI
ccs merge skills/think/SKILL.md --ai codex           # the Codex CLI
ccs merge skills/think/SKILL.md --ai prompt-only     # write the prompt; take it anywhere
ccs merge skills/think/SKILL.md --ai --ai-response answer.json   # apply an answer you carried back
ccs diff  skills/think/SKILL.md --ai                 # the proposal beside your result, in your diff tool
```

## What happens, in order

1. **The base.** ccs infers the common ancestor from the checkout's history, as it does for every merge. Without one, `--ai` refuses before any prompt is built: a two-way guess is not a merge. Supply a base with `--base-file`, or resolve the file by hand.
2. **The classification.** `git merge-file --diff3` has already done it. What git resolved is clean text and is never shown to the model. Every conflict hunk, a region both sides changed, is.
3. **The rules.** Your policy for the file, in your words, from `~/claude/ccs-merge-rules/<label>.md` (so `dotclaude/CLAUDE.md` reads `dotclaude/CLAUDE.md.md`), else `_default.md`, else none. Every paragraph gets an id (`R1`, `R2`, ...) the model cites when it drops a line. No rules file is a named state, printed with both places ccs looked, never a silent default.
4. **The prompt.** The rules with their ids, what ccs knows about the file's history (below), and each hunk with its lines named `O1..` (your live file), `B1..` (the ancestor), `T1..` (the payload's copy). A few context lines are shown and marked not selectable.
5. **The answer.** One JSON block naming lines per hunk, the rules it leaned on, and a sentence of why:
   ```json
   {"hunks": [{"hunk": 1, "lines": ["O1", "O2", "T3"], "rules": ["R2"], "rationale": "..."}]}
   ```
6. **The check.** Mechanical, before a byte is assembled: every id exists; no line text twice; each pane's order kept (an interleaving, never a reorder); a line left out is fine when a selected line is a rewrite of it, and otherwise needs a cited rule that exists in the loaded file; a base-only line brought back needs one too. A failure names the hunk and the id, and the answer is rejected: nothing is proposed, nothing copied. **A drop a rule authorised is reported, never silent** -- `hunk 3: dropped under R2 -- <the line>` -- and the same licence is written into the record, so the file-level check below (which reads your result against the two sides and knows nothing about your rules) does not refuse tomorrow what your own rule approved today. It is narrowed by exactly the lines you licensed and by nothing else: a loss no rule covers, an invented line, duplication or a pattern you fixed locally still stops the result.
7. **The proposal.** ccs assembles the file itself from the ids and runs the same validator every hand merge passes. The result lands in `<label>.merged-ai` in the merge workspace, beside your `<label>.merged`. If you had no result of your own there -- no `.merged` at all, or still the conflict-marked scaffold ccs seeded and nobody edited -- the proposal is copied into `.merged` so your diff tool and `--accept` have their file. The moment you edit `.merged`, it is yours: the proposal stays beside it and ccs says how far apart they are.
8. **The record.** `<label>.merged-ai.record.json`, beside the proposal: which backend, which rules and their hash, the hashes of the three sides, what was copied into `.merged` (once, never rewritten), and whether validation passed. Every line the report prints about the proposal is read from this record. "The bytes match" is only ever the signal; the record is the fact.

## What the model can and cannot do

It can select complete lines from a hunk's three panes and order them as an interleaving. It cannot write a line, cannot reorder within a side, cannot drop a line without a rule you wrote, and never chooses the base. That is by construction: the answer is ids, not text, and ccs does the assembly.

One consequence you will meet on real configuration: this house writes one line per paragraph, so a hunk is often one long line against another. Line selection can only take one side whole there. ccs says so, and prints what each side alone has:

```
hunk 1: both sides rewrote the same paragraph (1431 vs 1497 chars; 5 word-level differences).
        Line selection can only take one side whole.
        theirs adds:  "prioritization and ordering", "measuring and"
        ours keeps:   "keeps its name,", "because that is", "ranking"
```

That is what you would otherwise read out of two panes by eye. Fold the words in by hand, in the file.

## What ccs tells the model about the history

Evidence, never a decision. In the order ccs itself trusts things:

- the base it chose and how (inferred from the checkout's history, supplied from outside, or a sibling you opted into), with its commit date;
- the same hints the terminal prints (a regressed pattern, a convention drift);
- the other versions of the file in the checkout's history, nearest to your live file first, with their dates, and a caveat: distance is a weak ranking;
- whether the payload's copy in the checkout is committed or an uncommitted edit in its working tree;
- the checkout's position against its remote, as of the last fetch (`--ai` never fetches);
- whether your live tree is itself a git repository and what it says about this file, read and never written.

File modification times are deliberately absent: the payload's copy is materialised seconds before the merge and yours dates from the last `collect`, so neither is a fact about the content.

## Reading the report

The vocabulary is the merge verb's: **staged** means in the workspace, nothing installed.

| line | meaning |
|---|---|
| `staged <file> -- the AI's proposal (claude) at ...; validation passed; nothing installed` | a proposal was written this run; its rationale and rules follow |
| `    copied into .merged (you had no result of your own there); --accept asks before installing it` | the copy rule fired: `.merged` was absent, or the untouched seed |
| `staged <file> -- the AI's proposal, unchanged since <date>; nothing installed` | `.merged` is still exactly the copy |
| `staged <file> -- the AI's proposal from <date>; your live file has changed since` | a side moved after the proposal was made; re-run `--ai` |
| `    hunk 3: dropped under R2 -- <the line>` | a rule of yours authorised that line's removal; it is named so no drop is silent |
| `staged <file> -- yours; differs from the AI's proposal (3 lines); nothing installed` | the file is yours -- you edited the copy, or you had already resolved it before asking -- and `ccs diff <file> --ai` shows the difference |
| `NOT PROPOSED <file> -- the answer failed the check` | the reasons follow; the assembled file, if any, is left for your eyes |
| `prompt written <file> -- <path>` | prompt-only: answer it and re-run, or pass `--ai-response` |
| `refused <file> -- no common ancestor: a two-way guess is not a merge` | supply a base or resolve by hand |
| `not installed <file> -- the AI's proposal was not confirmed as reviewed` | `--accept` asked and was not told yes |

## `--accept` on a proposal you never touched

If `.merged` is still exactly what ccs copied there, `--accept` asks first:

```
skills/think/SKILL.md: this result is the AI's proposal, unchanged since ccs wrote it on 2026-09-03 (backend claude; rules ... @ a3f19c2).
  Nothing here has been through your eyes that ccs can see.
  If you have read it and want it installed: y.
  If you have not, answer N and open it (ccs diff skills/think/SKILL.md --ai).  [y/N]
```

A non-interactive run never says yes. A yes is recorded, so the same bytes are not asked twice. An edit you make and then undo reads as unchanged again, and asks again: ccs cannot tell "read and agreed" from "never opened", and does not pretend to.

## Backends, the cache, and privacy

- `prompt-only` costs nothing and sends nothing. The prompt is written under `~/claude/ccs-merge-rules/_prompts/`, and the report names the file to put the answer in (`<label>.merged-ai.response.json` in the workspace) or you pass `--ai-response FILE`. An answer in the workspace is applied only when `--ai` is on the command line, never by a bare `merge`.
- `claude` runs the Claude Code CLI; `codex` runs the Codex CLI. Both run from a throwaway directory, so a project's own instruction files never leak into a prompt about your configuration. Note that the Claude Code CLI still loads your global `CLAUDE.md`.
- **The prompt contains your configuration text** -- the hunks, the rules, the history lines. If that must not leave the machine, use `prompt-only` and a local model.
- Answers are cached under `~/claude/cache/ccs-ai/`, keyed on what the proposal was made from: the three sides, the rules file, how the base was chosen, and the structured history facts. A re-run with the same inputs is free; `--ai-refresh` asks again. Editing the wording of the dossier does not flush the cache; editing any input does.
- `ai_merge_backend` in `~/claude/ccs-config.json` names the backend `--ai` uses when the flag gives none. `ai_merge_command`, documented since 0.3.0 and never implemented, is no longer read; `ccs doctor` says so if it is set.

## Where things live

| | |
|---|---|
| the proposal | `~/claude/merge/ccs/<label>.merged-ai` |
| its record | `~/claude/merge/ccs/<label>.merged-ai.record.json` |
| a carried answer | `~/claude/merge/ccs/<label>.merged-ai.response.json` |
| your rules | `~/claude/ccs-merge-rules/<label>.md`, `_default.md` |
| written prompts | `~/claude/ccs-merge-rules/_prompts/<label>-<timestamp>.md` |
| the cache | `~/claude/cache/ccs-ai/` |

`<label>` in the workspace is the file's path with its separators flattened, as it already is for `.merged`: `skills/s.md` becomes `skills__s.md.merged-ai`. The rules and prompt paths keep the real shape, so the rules file for `skills/s.md` is `~/claude/ccs-merge-rules/skills/s.md.md` -- when there is no rules file, ccs prints both paths it looked at, so you never have to work that out from this table.

Nothing under the payload checkout is written by `--ai`.

## What is deliberately not in this pass

A second proposal file per backend (the record carries which backend made the one that exists); painting the proposal into BeyondCompare's output pane on `--relaunch` (the injection driver can, and will, in a later pass); a ranking of base candidates by what each would lose (`--base-search`); and the file-to-many-files remap of a monolithic `CLAUDE.md` across the layered components, which is its own design.

**A local model** is the other one, and it is coming: an endpoint like LM Studio's, answering on the machine so the prompt never leaves it -- the position between `prompt-only`'s "nothing leaves, and you carry the answer back by hand" and a CLI backend's "your configuration text goes to a hosted model". Both backends here are CLI-shaped (an executable on PATH, run as a subprocess); a local one is HTTP-shaped and needs its endpoint and model named in the configuration, so it is a later pass rather than a fourth name in the list. Nothing about the answer format changes: line ids and rule citations, with ccs assembling the file, is exactly the shape a small model can be held to.
