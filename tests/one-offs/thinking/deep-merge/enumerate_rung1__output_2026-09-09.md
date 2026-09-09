# What rung 1 looks like on the real workspace -- 2026-09-09

Workspace: `C:\Users\Extreme\claude\merge\ccs` (31 input sets, read only; copies under `C:\Users\Extreme\AppData\Local\Temp\deep-merge-measure\enumerate-rung1-yvny5bmr`).
Regions per `airung.split_regions` (by suffix); anchors per `airung.anchors` (the spans of git's mechanical result that differ from the base). A conflict hunk count above 0 means the mechanical text still carries diff3 markers, which the regions include as text.

| input set | suffix | base / mech lines | hunks | regions anchored/total | anchored lines / mech lines |
|---|---|---|---|---|---|
| `agents/dwp-background.md` | md | 108 / 108 | 0 | 1/17 | 10 / 108 |
| `agents/help.md` | md | 288 / 288 | 0 | 1/37 | 30 / 288 |
| `agents/oracle.md` | md | 292 / 292 | 0 | 1/17 | 4 / 292 |
| `claude-config/global.md` | md | 903 / 903 | 0 | 2/76 | 19 / 903 |
| `claude-config/machine.md` | md | 14 / 44 | 0 | 7/7 | 44 / 44 |
| `claude-config/platform.md` | md | 7 / 76 | 0 | 7/7 | 76 / 76 |
| `CLAUDE.md` | md | 1014 / 1016 | 0 | 6/92 | 73 / 1016 |
| `commands/addendum.md` | md | 67 / 67 | 0 | 1/5 | 31 / 67 |
| `commands/analysis.md` | md | 143 / 143 | 0 | 1/18 | 9 / 143 |
| `commands/ask.md` | md | 47 / 47 | 0 | 1/6 | 17 / 47 |
| `commands/collaborate1.md` | md | 129 / 129 | 0 | 1/15 | 5 / 129 |
| `commands/collaborate2.md` | md | 114 / 114 | 0 | 1/14 | 8 / 114 |
| `commands/collaborate3.md` | md | 132 / 132 | 0 | 1/15 | 10 / 132 |
| `commands/contextpostmortem.md` | md | 60 / 60 | 0 | 1/3 | 51 / 60 |
| `commands/deprecated/async-agent.md` | md | 81 / 81 | 0 | 2/7 | 18 / 81 |
| `commands/fullpostmortem-lean.md` | md | 72 / 72 | 0 | 1/10 | 6 / 72 |
| `commands/fullpostmortem.md` | md | 56 / 56 | 0 | 1/3 | 47 / 56 |
| `commands/longask.md` | md | 66 / 66 | 0 | 1/7 | 12 / 66 |
| `commands/minipostmortem.md` | md | 43 / 43 | 0 | 1/3 | 34 / 43 |
| `commands/postmortem.md` | md | 45 / 45 | 0 | 5/5 | 45 / 45 |
| `commands/prepcommit.md` | md | 135 / 135 | 0 | 1/11 | 15 / 135 |
| `commands/quick-ask.md` | md | 60 / 60 | 0 | 1/7 | 10 / 60 |
| `settings.local.json` | json | 6 / 36 | 0 | 1/1 | 36 / 36 |
| `skills/collabN-local/SKILL.md` | md | 198 / 198 | 0 | 1/22 | 8 / 198 |
| `skills/create-project/SKILL.md` | md | 370 / 449 | 0 | 7/39 | 154 / 449 |
| `skills/dev-workflow-process/SKILL.md` | md | 152 / 156 | 0 | 2/17 | 30 / 156 |
| `skills/double-check/SKILL.md` | md | 167 / 167 | 0 | 1/17 | 28 / 167 |
| `skills/github-issues-setup/SKILL.md` | md | 154 / 164 | 0 | 2/13 | 16 / 164 |
| `skills/think/SKILL.md` | md | 169 / 177 | 1 | 2/16 | 31 / 177 |
| `skills/verdict/SKILL.md` | md | 108 / 108 | 0 | 1/8 | 16 / 108 |
| `skills/whatnext/SKILL.md` | md | 180 / 180 | 0 | 4/13 | 64 / 180 |

**Totals:** 31 sets, 528 regions, 66 anchored (rung-1 territory), 1 conflict hunks.

| suffix | sets | regions | anchored | mechanical lines |
|---|---|---|---|---|
| json | 1 | 1 | 1 | 36 |
| md | 30 | 527 | 65 | 5576 |

## The anchored regions, per input set

### `agents/dwp-background.md`

- **3. Save the Document** (heading, lines 91-100, 10 lines; 1 changed by the merge)

### `agents/help.md`

- ****5. File Storage - CRITICAL IMPLEMENTATION**** (heading, lines 112-141, 30 lines; 3 changed by the merge)

### `agents/oracle.md`

- **Bootstrapping a New Vault** (heading, lines 49-52, 4 lines; 1 changed by the merge)

### `claude-config/global.md`

- **4. **Synthesis & Recommendation** (*SPCR: Result + PVMU*)** (heading, lines 392-406, 15 lines; 3 changed by the merge)
- **Postmortem Documentation Process** (heading, lines 427-430, 4 lines; 1 changed by the merge)

### `claude-config/machine.md`

- **Machine: plzwork** (heading, lines 1-4, 4 lines; 2 changed by the merge)
- **Windows Development Environment** (heading, lines 5-7, 3 lines; 2 changed by the merge)
- **System Architecture** (heading, lines 8-14, 7 lines; 6 changed by the merge)
- **Key Directories** (heading, lines 15-16, 2 lines; 1 changed by the merge)
- **Code Layout** (heading, lines 17-26, 10 lines; 10 changed by the merge)
- **Development Environment** (heading, lines 27-38, 12 lines; 12 changed by the merge)
- **Dazzle Command Shell** (heading, lines 39-44, 6 lines; 6 changed by the merge)

### `claude-config/platform.md`

- **Platform: Windows** (heading, lines 1-4, 4 lines; 2 changed by the merge)
- **Claude Code Specific Issues** (heading, lines 5-6, 2 lines; 2 changed by the merge)
- **Windows File Path Bug** (heading, lines 7-13, 7 lines; 7 changed by the merge)
- **Unicode / Codepage Issues in Generated Scripts** (heading, lines 14-32, 19 lines; 19 changed by the merge)
- **3. Null Device Redirection in WSL/Windows** (heading, lines 33-52, 20 lines; 20 changed by the merge)
- **4. Always Use PowerShell for Junctions/Symlinks (Never cmd.exe)** (heading, lines 53-72, 20 lines; 20 changed by the merge)
- **Experimental / One-Off Scripts (Windows)** (heading, lines 73-76, 4 lines; 4 changed by the merge)

### `CLAUDE.md`

- **Storage Territory: `~/.claude/` vs `~/claude/`** (heading, lines 128-150, 23 lines; 2 changed by the merge)
- **1. **Problem Analysis & Implementation Planning** (*SPCR: Story*)** (heading, lines 460-475, 16 lines; 1 changed by the merge)
- **Postmortem Template** (heading, lines 543-546, 4 lines; 1 changed by the merge)
- **General Postmortems** (heading, lines 690-699, 10 lines; 1 changed by the merge)
- **Examples** (heading, lines 704-719, 16 lines; 2 changed by the merge)
- **Storage Location** (heading, lines 739-742, 4 lines; 1 changed by the merge)

### `commands/addendum.md`

- **Instructions** (heading, lines 11-41, 31 lines; 1 changed by the merge)

### `commands/analysis.md`

- **Output** (heading, lines 122-130, 9 lines; 1 changed by the merge)

### `commands/ask.md`

- **The script handles all escaping internally** (heading, lines 22-38, 17 lines; 1 changed by the merge)

### `commands/collaborate1.md`

- **File Naming Convention** (heading, lines 82-86, 5 lines; 1 changed by the merge)

### `commands/collaborate2.md`

- **File Naming Convention** (heading, lines 87-94, 8 lines; 1 changed by the merge)

### `commands/collaborate3.md`

- **File Naming Convention** (heading, lines 96-105, 10 lines; 1 changed by the merge)

### `commands/contextpostmortem.md`

- **Session Context: "$ARGUMENTS"** (heading, lines 10-60, 51 lines; 1 changed by the merge)

### `commands/deprecated/async-agent.md`

- **What's Happening:** (heading, lines 56-61, 6 lines; 1 changed by the merge)
- **Check Progress:** (heading, lines 62-73, 12 lines; 3 changed by the merge)

### `commands/fullpostmortem-lean.md`

- **4. Save Location** (heading, lines 52-57, 6 lines; 1 changed by the merge)

### `commands/fullpostmortem.md`

- **Information to Document:** (heading, lines 10-56, 47 lines; 1 changed by the merge)

### `commands/longask.md`

- **Documentation Requirements** (heading, lines 44-55, 12 lines; 3 changed by the merge)

### `commands/minipostmortem.md`

- **Current Context: "$ARGUMENTS"** (heading, lines 10-43, 34 lines; 1 changed by the merge)

### `commands/postmortem.md`

- **preamble** (preamble, lines 1-5, 5 lines; 1 changed by the merge)
- **Postmortem Analysis** (heading, lines 6-13, 8 lines; 5 changed by the merge)
- **1. Read the situation** (heading, lines 14-22, 9 lines; 5 changed by the merge)
- **2. Choose a variant** (heading, lines 23-37, 15 lines; 11 changed by the merge)
- **3. Invoke it** (heading, lines 38-45, 8 lines; 7 changed by the merge)

### `commands/prepcommit.md`

- **Phase 7: Hand Off to /commit** (heading, lines 102-116, 15 lines; 5 changed by the merge)

### `commands/quick-ask.md`

- **Documentation Requirements** (heading, lines 41-50, 10 lines; 3 changed by the merge)

### `settings.local.json`

- **{** (paragraph, lines 1-36, 36 lines; 32 changed by the merge)

### `skills/collabN-local/SKILL.md`

- **File Naming Convention** (heading, lines 154-161, 8 lines; 1 changed by the merge)

### `skills/create-project/SKILL.md`

- **Phase 1b: Claim issues #1 and #2 IMMEDIATELY (order matters)** (heading, lines 49-69, 21 lines; 21 changed by the merge)
- **Phase 3: Add git-repokit-common as Subtree** (heading, lines 102-129, 28 lines; 20 changed by the merge)
- **Sign the two commits subtree just made (it bypasses commit.gpgsign)** (heading, lines 130-159, 30 lines; 29 changed by the merge)
- **Phase 4: Install Git Hooks** (heading, lines 160-170, 11 lines; 1 changed by the merge)
- **Phase 7: Initialize Private Folder** (heading, lines 211-227, 17 lines; 2 changed by the merge)
- **Create Issues #1 and #2** (heading, lines 269-298, 30 lines; 5 changed by the merge)
- **Gotchas & Lessons Learned** (heading, lines 426-442, 17 lines; 3 changed by the merge)

### `skills/dev-workflow-process/SKILL.md`

- **Step 0.5: Ground truth FIRST** (heading, lines 60-73, 14 lines; 2 changed by the merge)
- **Stage 3: Solutions Evaluation (Content)** (heading, lines 95-110, 16 lines; 2 changed by the merge)

### `skills/double-check/SKILL.md`

- **Phase 1 — EXTRACT (the prioritized sweep)** (heading, lines 34-61, 28 lines; 1 changed by the merge)

### `skills/github-issues-setup/SKILL.md`

- **WHEN to run this: immediately after the repo exists, BEFORE the first push** (heading, lines 23-32, 10 lines; 10 changed by the merge)
- **Prerequisites** (heading, lines 33-38, 6 lines; 1 changed by the merge)

### `skills/think/SKILL.md`

- **What this is, and when it fires** (heading, lines 14-23, 10 lines; 2 changed by the merge)
- **The root and the atom** (heading, lines 50-70, 21 lines; 8 changed by the merge)

### `skills/verdict/SKILL.md`

- **The procedure** (heading, lines 37-52, 16 lines; 4 changed by the merge)

### `skills/whatnext/SKILL.md`

- **/whatnext — where are we, and what should we do about it?** (heading, lines 7-16, 10 lines; 1 changed by the merge)
- **Step 2: Read the state** (heading, lines 60-91, 32 lines; 2 changed by the merge)
- **Step 3: Recommend with evidence, then stop** (heading, lines 92-104, 13 lines; 1 changed by the merge)
- **Anti-patterns** (heading, lines 172-180, 9 lines; 1 changed by the merge)

