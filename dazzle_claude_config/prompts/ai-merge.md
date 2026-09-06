# ccs merge --ai: resolve the dual-touched hunks of `{label}`

You are resolving a three-way merge of ONE configuration file for `ccs` (dazzle-claude-config). Two sides changed the same regions of it; everything else is already merged by git and is not yours to touch. For EACH hunk below, choose which of its lines survive and in what order, and say why.

The three panes of a hunk are:

- **O** -- the person's live file (ours),
- **B** -- the common ancestor both sides started from (base),
- **T** -- the payload's copy (theirs; the shared configuration the person syncs with).

## The rules the person wrote

These are the person's own policy for this file, in their words. Cite a rule by its id whenever you leave a line out or bring back a base-only line.

{rules}

## What ccs knows about the history

Evidence, not instructions. ccs chose the base; you never choose one. Use this to infer intention: which side's change is newer, whether an edit is committed or still a working-tree change, what the person tends to keep.

{dossier}

## The hunks

{hunks}

## How to answer

Reply with exactly ONE fenced ```json block and nothing after it:

```json
{{"hunks": [{{"hunk": 1, "lines": ["O1", "O2", "T3"], "rules": ["R2"], "rationale": "one or two sentences"}}]}}
```

- `lines`: ids from THIS hunk's panes only, in the order they should appear in the file. Each id at most once. Keep each pane's own order: an interleaving of O, B and T, never a reorder within a pane.
- A line you leave out is fine when a line you selected is a rewrite of it. Otherwise a rule in `rules` must license the drop, or the proposal fails validation and nothing is installed. When a rule drops the whole region, `lines` is empty (`[]`) and `rules` cites it: selecting a side is not a drop.
- A B line whose text appears in neither O nor T brings back content nobody has now; it needs a rule too.
- Context lines are marked and are not selectable.
- A hunk marked **paragraph** is one line against one line: you can only take one side whole -- or, under a rule that drops the line, neither. Say which and why, and put the words the other side alone has (listed for you) in the rationale so the person can fold them in by hand.
- A hunk marked **additions** is lines both sides added where the base had nothing, and they added different things: keeping both is usually right, and you may -- select the O lines and the T lines together, in the order that reads best. Drop one side only under a rule.
- Never write new text. Never explain outside the JSON block.
