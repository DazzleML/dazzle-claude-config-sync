# `ccs merge --ai`: a proposal beside your file

A three-way merge leaves you the hunks both sides changed. `--ai` asks a model to resolve exactly those hunks, under rules you wrote, and puts its answer in a second file beside yours. It installs nothing. You look, you edit or you don't, and `--accept` installs your file, as it always has.

```
ccs merge skills/think/SKILL.md --ai                 # prompt-only unless ai_merge_backend says otherwise
ccs merge skills/think/SKILL.md --ai claude          # the Claude Code CLI
ccs merge skills/think/SKILL.md --ai codex           # the Codex CLI
ccs merge skills/think/SKILL.md --ai lmstudio        # a local server; nothing leaves your network
ccs merge skills/think/SKILL.md --ai ollama          # the same, at Ollama's address
ccs merge skills/think/SKILL.md --ai openrouter      # a hosted provider; the key from OPENROUTER_API_KEY or ~/claude/keys/openrouter.env
ccs merge skills/think/SKILL.md --ai prompt-only     # write the prompt; take it anywhere
ccs merge skills/think/SKILL.md --ai --ai-response answer.json   # apply an answer you carried back
ccs merge skills/think/SKILL.md --ai claude,deep     # the recipe, then the deep step on the same backend
ccs merge skills/think/SKILL.md --ai deep:lmstudio --ai-scope file   # the deep step on a local model, allowed the whole file
ccs diff  skills/think/SKILL.md --ai                 # the proposal beside your result, in your diff tool
ccs diff  skills/think/SKILL.md --ai --variant 1     # the deep step's answer beside your result
```

## What happens, in order

1. **The base.** ccs infers the common ancestor from the checkout's history, as it does for every merge. Without one, `--ai` refuses before any prompt is built: a two-way guess is not a merge. Supply a base with `--base-file`, or resolve the file by hand.
2. **The classification.** `git merge-file --diff3` has already done it. What git resolved is clean text and is never shown to the model. Every conflict hunk, a region both sides changed, is.
3. **The rules.** Your policy for the file, in your words, from `~/claude/ccs-merge-rules/<label>.rules.md` -- the label flattened, so `dotclaude/CLAUDE.md` reads `dotclaude__CLAUDE.md.rules.md`, one flat file you can create without making a directory -- else `_default.md`, else none. Every paragraph gets an id (`R1`, `R2`, ...) the model cites when it drops a line. No rules file is a named state, printed with both places ccs looked, never a silent default.
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

That is the **recipe**, and it is deliberately shallow: everything git merged on its own is never shown to the model. The case it cannot see is the one where two people's changes each look fine and are wrong together -- one person changes what a function returns, another changes the code that calls it, git merges the two cleanly, and the result is wrong without an error. For that there is a second pass.

## The deep step: `--ai claude,deep`

`--ai` takes a plan: one or more steps, in order. `claude,deep` runs the recipe on claude and hands its result to the **deep step** on the same backend; `deep` alone runs on the configured backend and inserts the recipe before itself; `deep:lmstudio` names its own. The deep step reads the whole merged file -- the recipe's proposal, or git's clean merge when there was nothing to decide -- for meaning, and it may write text. So its guarantee is about *where*, not *what*:

- **It works in a disposable copy.** A worktree of the payload checkout beside a copy of the live component, with the merged file written in. A backend with tools (`claude`, `codex`) edits there, under the CLI's own sandbox flag; a backend without them (`lmstudio`, `ollama`, `openai`, `openrouter`) is shown the file and the two changes and answers with a diff, which git applies to a copy. The real checkout and the real live tree are hashed before and after the call; a backend that changed either has its answer discarded, and the report names the file.
- **It may edit only as far as you allow.** `--ai-scope hunk` (the default) is the changed regions and their surrounding code -- the section under the same heading, the enclosing function or block; `file` is this file only; `neighbours` is this file and its neighbouring files (the same component's files, the files the payload's commit touched with it, the files that name it); `project` is anything under the checkout or this component. Every edit the model made is placed on that ladder. Within the scope you allowed, its answer is kept as a numbered variant, `<file>.merged-ai.1`, beside the recipe's `<file>.merged-ai`; beyond it the answer is **not kept**, and the report lists the edits it would have made so you can see what a wider scope would buy. A backend without tools can reach `file` but not `neighbours` or `project`, and says so before any call.
- **An unchanged file is a correct answer.** A deep step that changes nothing says `nothing to change` and is not pending work.
- **No automatic winner.** Every answer has its own line in the report and its own guarantees line: the recipe's says every line came from one of the three sides and git's clean regions were never sent; the deep step's says this variant may contain text no side wrote, where the ladder allowed edits and where they landed. The record beside your file holds them all, and which one becomes the file is your decision, made the way it always was: put the bytes you want in `.merged` and run `--accept`. `ccs diff <file> --ai --variant 1` opens the deep answer beside yours.
- **`--accept` asks with the right guarantees.** A `.merged` that equals a deep variant is read as the AI's, not yours, and the question names that answer and prints its guarantees line; the record's choice moves to it only on a yes. For a deep variant the usual loss check runs as a tripwire -- printed, never refusing -- because such a variant may legitimately hold text neither side wrote; conflict markers, a regressed pattern and a credential shape still refuse.
- **Nothing is cached.** A run that edited files in a copy is not reproducible from its inputs the way a line selection is, and asking twice means asking twice.

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
| `    hunks: 1 both sides changed -- the model's; 19 lines git resolved on its own, never sent` | the classification counts, always the first line under the headline (also after `prompt written`): what the model was given, and how much of the file it never saw |
| `    copied into .merged (you had no result of your own there); --accept asks before installing it` | the copy rule fired: `.merged` was absent, or the untouched seed |
| `staged <file> -- the AI's proposal, unchanged since <date>; nothing installed` | `.merged` is still exactly the copy |
| `staged <file> -- the AI's proposal from <date>; your live file has changed since` | a side moved after the proposal was made; re-run `--ai` |
| `    hunk 3: dropped under R2 -- <the line>` | a rule of yours authorised that line's removal; it is named so no drop is silent |
| `    guarantees: every line came from one of the three sides ...` | what protects this answer; a deep step's variant carries a different line (`this variant may contain text no side wrote; the ladder allowed edits in ...`) |
| `    backend: loaded with a 200,192-token context; ...` | the backend's own "yes, but" from its readiness check, under the answer it applies to (also beside an `ai failed` line, where a timeout is usually that warning coming true); nothing is printed when there is none |
| `staged <file> -- the AI's answer <file>.merged-ai.1 (deep via claude; needed hunk, hunk allowed); nothing installed` | the deep step's variant, kept because every edit landed within the scope you allowed; `files touched`, its guarantees line, its summary and its edits with reasons follow |
| `ai <file> -- nothing to change (deep via claude): the merged file stands` | the deep step found the two changes consistent; not pending work |
| `NOT KEPT <file> -- the model's edits needed neighbours scope and hunk was allowed -- nothing kept; ...` | the deep step reached beyond the scope (or changed a real file); the edits it would have made follow, and the file is pending |
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

A backend is a *preset*: a name over one of three ways of reaching a model. The CLIs (`claude`, `codex`) run an executable; the servers (`lmstudio`, `ollama`, `openai`, `openrouter`) speak the OpenAI API to an address -- the same code with a different endpoint and, for the hosted ones, a key. Local versus remote is configuration, never a different feature. `ccs doctor` builds the configured preset and prints what it says about itself: whether its executable was found, what model is loaded and how big its window is, or where it looked for its key and where it found one -- and whether your text stays on your network.

- `prompt-only` costs nothing and sends nothing. The prompt is written under `~/claude/ccs-merge-rules/_prompts/`, and the report names the file to put the answer in (`<label>.merged-ai.response.json` in the workspace) or you pass `--ai-response FILE`. An answer in the workspace is applied only when `--ai` is on the command line, never by a bare `merge`. It is a mode, not a backend.
- `claude` runs the Claude Code CLI and asks for Opus 5 (`claude-opus-5`) unless `ai_merge_model` says otherwise -- a merge should not silently inherit whatever model the CLI's session defaults to; `codex` runs the Codex CLI with its own default. Both run in a throwaway directory handed to the child, so a project's own instruction files never leak into a prompt about your configuration. Note that the Claude Code CLI still loads your global `CLAUDE.md` -- on a box with a large one, that is most of the cost of every call. `claude-strict` and `codex-strict` ask for the answer's schema on the command line instead of in the prompt; they are experiments, not the defaults.
- **`lmstudio` and `ollama` ask a model on your own machine**: a real model answers, and nothing leaves your network. `lmstudio` speaks to `http://127.0.0.1:1234/v1` (the IPv4 literal on purpose, because LM Studio binds IPv4-only on Windows and `localhost` can resolve to `::1` first and hang), `ollama` to `http://127.0.0.1:11434/v1`; `ai_merge_endpoint` points either at another server, on this box or another one in the house. Start the server first: in LM Studio that is the **Developer** tab, *Start Server*; the app being open is not enough, and `ccs doctor` says *no model server at … -- start the local server (in LM Studio: the Developer tab)* rather than pretending a CLI is missing. Naming a model the server does **not** have makes LM Studio load it from disk, so ccs checks the id first and refuses with the list of what is actually loaded. The request asks for a strict JSON schema, which a small local model cannot answer with prose.
- **`openrouter` and `openai` are the same transport over the wire.** A provider that does not honour the schema for the model it routed to answers with an HTTP error carrying its own words, and ccs does not retry without the schema.
- **Where the key comes from.** Three places, read in this order, and the first that has it wins: a file you name with `ai_merge_api_key_file`; the environment variable the preset names (`OPENROUTER_API_KEY`, `OPENAI_API_KEY`) or the one `ai_merge_api_key_env` names; and `~/claude/keys/<preset>.env` -- `~/claude/keys/openrouter.env` for openrouter -- which is user territory, one file per provider, and never part of the payload. A key file holds `NAME=value` lines, where `NAME` is that variable (`OPENROUTER_API_KEY=sk-or-v1-...`); an `export ` prefix, quotes, `#` comments and blank lines are fine, and a file holding only the key works too. The value is read when a request is made and never enters the config file, the cache, a record or a report -- a record names the file it came from (`keyfile:openrouter.env`), never its contents. `ccs doctor` says where it looked and where it found the key (`key from OPENROUTER_API_KEY`, or `key from <path>`), and when it found none it names the variable and every file with why each gave nothing. Keep a key file readable by you alone; on Linux and macOS ccs warns when it is not. **Keeping keys out of the payload:** `ccs collect` refuses a file that carries an OpenRouter or OpenAI key shape, as it always has for other credentials; a manifest entry may say `"allow_secrets": true` to collect a keys file on purpose, and the report then prints one `allowed <path>` line per such file -- the path, never the content -- so the choice is as visible as a refusal would have been.
- `ai_merge_model` names the model, for every preset that is one: the CLIs take it on their command line, the servers in the request. The report says which model actually answered and which parts of the request the backend enforced.
- **The prompt contains your configuration text** -- the hunks, the rules, the history lines. If that must not leave your network, use a local server (a real model answers, on your hardware) or `prompt-only` (nothing is sent at all, and you carry the answer back yourself).
- Answers are cached under `~/claude/cache/ccs-ai/`, keyed on what the proposal was made from -- the three sides, the rules file, how the base was chosen, the structured history facts -- and on who was asked: the backend's own identity, which includes the model and the address. A re-run with the same inputs is free; `--ai-refresh` asks again. Editing the wording of the dossier does not flush the cache; editing any input, or changing the model, does.
- `ai_merge_backend` in `~/claude/ccs-config.json` names the preset `--ai` uses when the flag gives none. `ai_merge_command`, documented since 0.3.0 and never implemented, is no longer read; `ccs doctor` says so if it is set.

## Where things live

| | |
|---|---|
| the proposal | `~/claude/merge/ccs/<label>.merged-ai` |
| its record | `~/claude/merge/ccs/<label>.merged-ai.record.json` |
| a carried answer | `~/claude/merge/ccs/<label>.merged-ai.response.json` |
| your rules | `~/claude/ccs-merge-rules/<label>.rules.md`, `_default.md` |
| written prompts | `~/claude/ccs-merge-rules/_prompts/<label>-<timestamp>.md` |
| the cache | `~/claude/cache/ccs-ai/` |
| a hosted preset's key | `~/claude/keys/<preset>.env`, unless the environment variable or `ai_merge_api_key_file` has it |

`<label>` everywhere above is the file's path with its separators flattened, and it is the same rule in all three places: `skills/s.md` becomes `skills__s.md.merged-ai` in the workspace, `skills__s.md-<timestamp>.md` under `_prompts/`, and `skills__s.md.rules.md` for its rules. Nothing nests, so there is never a directory to create first -- and when there is no rules file, ccs prints both paths it looked at, so you never have to work it out from this table.

Nothing under the payload checkout is written by `--ai`.

## What is deliberately not in this pass

A second proposal file per backend (the record carries which backend made the one that exists); painting the proposal into BeyondCompare's output pane on `--relaunch` (the injection driver can, and will, in a later pass); a ranking of base candidates by what each would lose (`--base-search`); and the file-to-many-files remap of a monolithic `CLAUDE.md` across the layered components, which is its own design.

**Which backends have been asked for real.** The pipeline is proven against fakes for every transport, and against a golden set of nine conflict shapes in canned mode (`tests/test_golden_ai_merge.py`); running that set live against a preset (`CCS_GOLDEN_AI=lmstudio`) is how a backend earns its place, and the matrix it prints is the record. As of this pass, every preset that is a model has matched all nine fixtures live: claude (Opus 5), codex (its default model), lmstudio (a 27B Qwen) and openrouter (gemini-2.5-flash, nine answers in nine seconds of model time, on the order of a cent). The local model answered the nine in twenty seconds on one GPU, and its one miss on the first pass was the prompt's wording, not the model's judgement -- which is the measurement the golden set exists to take.

**Two line-selection answers in one run** (`--ai claude,codex`, issue #58) is not built and is refused as such; `--ai claude,deep` is the plan grammar that exists, and the record is already shaped for more (N answers, one chosen), so building the rest later migrates nothing in your workspace.
