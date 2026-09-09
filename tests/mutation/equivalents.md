# Triaged equivalent / don't-care survivors

Guarded authority: entries expire when the file hash heading no longer matches
git hash-object (first 12). Only separated-generation runs (modes 1-2) write here.

## dazzle_claude_config/merge.py @ 5353ee230030

- M2 (v0.5.17 sweep): `if cap:` -> `if cap is not None:` in `tool_resume`.
  **equivalent** -- `by_name` is always built by `_resume_table`, which stores
  a capability only when `isinstance(cap, str) and cap`, so an empty string
  can never be present to distinguish the two conditions. (2026-09-01, mode 1;
  swept against the staged index exported to a scratch root because another
  session was active in the repo.)

## dazzle_claude_config/merge.py @ bd11a66513bb (STALE -- hash no longer matches; re-triage before reuse)

- m3 (v0.4.0 sweep): original drops `if live.is_file():` before the
  directory-member yield. **equivalent** -- d.modified guarantees both sides
  existed at diff time; only a TOCTOU race between diff_all and the yield could
  expose it, which is outside the testable contract. (2026-08-21, mode 1;
  re-triaged under the v0.4.1 hash: the line is unchanged at merge.py:173/180.)
- M1 (v0.4.1 sweep): `shas.insert(0, head)` -> `shas.append(head)`.
  **don't-care** -- the branch fires only when HEAD is TREESAME for the path
  (omitted from `git log -- path`), so HEAD's blob equals the first listed
  commit's; the returned base bytes are identical and only the sha7 in the
  evidence label differs. (2026-08-21, mode 1.)
- M3 (v0.4.1 sweep): `if cand == ours_n:` -> `if cand == ours_n and cand != theirs_n:`.
  **equivalent** -- every caller (`two_way_labels`, `_classify`, merge) reaches
  `infer_base` only for files where ours != theirs, so no candidate can equal
  both. (2026-08-21, mode 1.)

## dazzle_claude_config/cli.py @ f31eaf694421

- M10 (v0.4.1 sweep): `if shown.returncode != 0 or not shown.stdout:` ->
  `... and not shown.stdout:`. **don't-care** -- the two differ only for an
  EMPTY committed file (rc 0, empty stdout); `infer_base` skips empty blobs,
  so both paths end in non-attribution. (2026-08-21, mode 1.)

## dazzle_claude_config/basefind.py @ dd3c133d6ee9

- M4 (v0.4.3 sweep): `Region(..., [ours[b2o[i]] ...])` -> `[base[i] ...]`.
  **equivalent** -- `b2o` is built from `equal` opcodes only, so every mapped
  ours line is byte-identical to its base line; the region text is the same
  list either way. (2026-08-22, mode 1.)
- M5 (v0.4.3 sweep): `if any(mask[at:at+n])` -> `if all(...)` in
  `wrap_clean_regions`. **equivalent** -- a region is found by `_find` as a
  contiguous run of its own lines, none of which is a marker line, so its span
  can never cross a hunk boundary; the mask is therefore uniform over the span
  and `any` == `all`. (2026-08-22, mode 1.)

## dazzle_claude_config/syncmap.py @ 8694a5c0fd05

- M9 (v0.4.3 sweep): `rel_in_scope`: `if sub_prefix is None` -> `if not sub_prefix`.
  **equivalent** -- the only producer of a sub-prefix is `only_scope`, which
  strips trailing slashes before slicing, so `--only dotclaude/skills/` is
  the whole entry (`(True, None)`) and an empty-string sub-prefix can never
  reach `rel_in_scope`. Pinned by the trailing-slash case in
  `test_only_scope`. (2026-08-22, mode 1.)

## dazzle_claude_config/gitops.py @ 25ced351a047

- G3 (v0.5.8 sweep): `dirty_paths` parses the porcelain line with `line[3:]`;
  the mutant uses `line[2:]`. **equivalent** -- both slices are followed by
  `.strip()`, and porcelain's format is two status columns, one space, then the
  path, so `line[2:].strip()` and `line[3:].strip()` return the identical
  string for every status code including `??`. No input can separate them.
  (2026-08-26, diff-scoped sweep.)

## dazzle_claude_config/gitops.py @ e58d26e552bb

- H3 (v0.5.9 sweep): the rename unpack `old_p, new_p = path.split(" -> ", 1)`
  with the two names swapped. **equivalent** -- both names are added to the
  same set on the next two lines and nothing downstream distinguishes them,
  so no input can separate the two spellings. Predicted equivalent in the
  spec before the run rather than triaged afterwards. (2026-08-26.)

## dazzle_claude_config/cli.py @ 0f9d159143e3

- `if plan.exists and plan.unknown:` -> `if plan.exists or plan.unknown:`
  -- **equivalent** (2026-08-28, generation mode 1). `plan_config` returns
  `unknown=[]` for a file that does not exist, so the two forms cannot differ
  given its contract. The `plan.exists` half is a guard documenting that
  contract rather than dead code, and removing it would make the doctor
  section depend on an invariant stated nowhere. Verified by calling
  `plan_config` on an empty directory: `exists=False, unknown=[]`.
  Re-triage if `plan_config` ever reports unknown keys for an absent file.

## dazzle_claude_config/ailib.py @ 2eeaa3628001

- M3 (v0.5.21 sweep, ailib facade): `if not text:` -> `if text is None:` in
  `parse_json_block`. **equivalent** -- an empty string reaches
  `_JSON_FENCE.findall("")`, which returns `[]`, and the next guard
  (`if not blocks: return None`) yields the same `None` the short-circuit
  did. No input distinguishes the two forms. (2026-09-03, generation mode 1;
  9 of 11 killed in round 1, M8 killed by `test_invoke_forwards_verbose_and_timeout_by_name`
  written on the spot.) Re-triage if the empty-string path ever gains a
  different meaning (e.g. an "empty answer" diagnostic).
- N6 (v0.5.21 sweep, round 2): `except ValueError:` -> `except
  json.JSONDecodeError:` around `json.loads(blocks[-1])`. **equivalent** --
  `blocks[-1]` is always a `str` (a regex group), and for a `str` argument
  `json.loads` raises only `JSONDecodeError`, which is the `ValueError`
  subclass; no other `ValueError` can reach the handler. (2026-09-03, mode 1;
  round 2 of 2: N1, N2, N3, N7, N8 were killable and became tests.)
  Re-triage if `parse_json_block` ever passes bytes or a custom decoder.

## dazzle_claude_config/aimerge.py @ 41aa6d428b6c

- M5 (v0.5.21 sweep, the hunk parser): the `if startswith(BASE_MARK) ...
  elif startswith(SEP_MARK)` pair in `parse_diff3` swapped. **equivalent** --
  the two prefixes (`|||||||` and `=======`) are disjoint, so no line takes
  both branches and the order of the tests cannot change which pane a line
  lands in. (2026-09-03, generation mode 1; 6 of 14 killed in round 1, the
  seven other survivors became tests.) Re-triage if a marker ever becomes a
  prefix of another.
- N4 (round 2): the `segments[k + 1].kind == "clean"` clause dropped from the
  after-context loop. **equivalent** -- when the following segment is a hunk
  its `lines` is the empty default, so `[:context]` of it is `[]`, exactly
  what the guarded form leaves in place. (2026-09-03, mode 1; N1, N7, N10
  became tests.) Re-triage if `Segment.lines` ever carries text for a hunk.

## dazzle_claude_config/airecord.py @ 43afd72b17ba

- M7 (v0.5.21 sweep, the provenance record): `path.is_file()` ->
  `path.exists()` at the top of `load`. **equivalent** -- a directory at
  the record path then reaches `read_text`, which raises an `OSError`
  (`IsADirectoryError` / `PermissionError`) that the very next `except
  (OSError, ValueError)` turns into the same `None`. (2026-09-03, mode 1;
  M4, M6, M8, M9, M10 became tests.) Re-triage if the read ever moves out
  of that `try`.

## dazzle_claude_config/aiprompt.py @ b1978d2ca7be

- M5 (v0.5.21 sweep, the proposal check): `b <= a` -> `b < a` in the
  per-pane order test. **don't-care** -- the only answer the two forms
  judge differently is a repeated id (`O1, O1`), which the duplicate-text
  check has already refused; the mutation changes which second failure
  line accompanies the first, never whether the answer is rejected.
  (2026-09-03, mode 1; M3, M4, M6, M8, M13, M14, M15 became tests.)
  Re-triage if the duplicate-text check ever stops covering repeated ids.

## dazzle_claude_config/aistep.py @ b2ac0e2d8575

- N4 (v0.5.21 sweep, the AI step, round 2): `TOOL_NAME = "ccs-merge"` ->
  `"ccs"`. **don't-care** -- the cache namespace only has to be one stable
  string that another tool's fingerprints cannot share; its spelling is
  not a contract, and no observable behaviour of ccs depends on which
  string it is. (2026-09-03, mode 1; N2, N3, N6, N9, N11 became tests.)
  Re-triage if the cache directory is ever shared with another tool whose
  namespace could be the same word.

## dazzle_claude_config/cli.py @ f1449234833d

- M14 (v0.5.21 sweep, the --ai wiring): the `or aistep.PROMPT_ONLY`
  fallback in `_ai_options` -> `or "auto"`. **equivalent under the default**
  -- `userconfig.KEYS["ai_merge_backend"]` defaults to `prompt-only`, so
  `cfg.get(...)` is never empty unless a config file sets the key to null;
  the fallback is defence, not a path. (2026-09-03, mode 1.) Re-triage if
  the key's default ever becomes None.
- M15 (same sweep): the two exit-code checks after `unresolved` swapped
  (`EXIT_NO_BASE` before `EXIT_DRIFT` for a pending prompt or a declined
  proposal). **don't-care** -- both fire only when a run holds a no-base
  refusal AND a pending/declined item at once, both codes mean "work
  pending", and the refusal line is printed either way. (2026-09-03,
  mode 1.) Re-triage if a caller ever branches on 2 vs 1 for --ai.

## dazzle_claude_config/merge.py @ 85a6412c372e

- N6 (v0.5.21 sweep, the --ai wiring, round 2): `_line_delta(merged,
  proposal)` -> `_line_delta(proposal, merged)`. **equivalent** -- the count
  is `max(i2 - i1, j2 - j1)` per non-equal opcode, symmetric in its two
  sequences. (2026-09-03, mode 1.) Re-triage if the count ever weights the
  sides differently.
- N1 (same round): `if i.mergeable and i.base is None` -> `if i.base is
  None` in the `--ai` refusal. **don't-care** -- the only item it reaches
  that the guarded form does not is one already refused for another reason
  (a render/compose strategy, a settled seed), whose `reason` it rewords;
  the item is refused either way and no exit code changes. Not worth a
  fixture with a refused-by-strategy entry. (2026-09-03, mode 1.)
  Re-triage if a refusal reason is ever machine-read.

## dazzle_claude_config/merge.py @ 2d89ce0d4452

- M1 (v0.5.21 sweep, the dossier): `[:max_commits + 1]` -> `[:max_commits]`
  in `infer_base`'s commit window. **don't-care** for this unit -- the `+ 1`
  predates the dossier (the window is HEAD plus `max_commits` older
  versions) and only the 26th-oldest candidate moves; the unit re-parsed
  the line without changing the window. A 26-commit fixture belongs to
  the base-search work (#23). (2026-09-03, mode 1.)
- M3 (same sweep): `if l.strip()` dropped from the `pairs` comprehension.
  **equivalent** -- a blank line becomes `[]`, which `if p` drops from
  `shas` and `len(p) == 2` drops from `dates`. Re-triage if either filter
  goes.
- M4 (same sweep): `rc != 0 or not out` -> `rc != 0 and not out` on the
  `git log` guard. **equivalent in practice** -- a failing `git log` writes
  to stderr, and `_git` returns stdout only, so `rc != 0` always comes with
  empty `out`. Re-triage if `_git` ever merges stderr into its result.
- M7 (same sweep): the porcelain path slice `line[3:]` -> `line[2:]`.
  **equivalent** -- the extra character is the separator space, which the
  `.strip()` that follows removes. Re-triage if the strip is removed.
- N2 (same sweep, round 2): the commit window `[:max_commits + 1]` ->
  `[1:max_commits + 1]` (HEAD dropped from the log's list). **equivalent**
  -- the next lines re-insert HEAD at the front whenever it is absent
  (`git log -- path` omits a TREESAME merge commit at HEAD, which is why
  that line exists), so the searched list is the same. Re-triage if the
  HEAD re-insertion ever goes.

## dazzle_claude_config/merge.py @ 274453340615

- merge-7 (v0.5.21 sweep, the doctor lines + the copy rule, mode 1,
  2026-09-03): `untouched = (not fresh and stamp.exists() and not
  _differs_bytes(merged, stamp))` -> the `stamp.exists()` clause dropped.
  **equivalent** -- with no `.seed` on disk `_differs_bytes` catches the
  `OSError` and returns True (merge.py:1079), so `untouched` is False
  either way; the clause states the intent and saves a raise. Re-triage if
  `_differs_bytes` ever stops treating an unreadable file as differing.

## dazzle_claude_config/_vendor/ailib/backends/lmstudio.py @ eb732125611a

- m3 (v0.5.21 sweep, the lmstudio backend, mode 1, 2026-09-04):
  `live is None and _model not in listed` -> `or`. **equivalent in
  practice** -- the two differ only when a model is reported LOADED by the
  native API but absent from `/v1/models`. LM Studio lists every loaded
  model, so that state is unreachable there. Re-triage if a server turns up
  that enumerates loaded models it does not list.

## dazzle_claude_config/livegit.py @ c1e9c2453f02

- M19 (v0.5.21 sweep): the `rc != 0` half of the `rev-parse` guard dropped.
  **equivalent in practice** -- a failing `rev-parse --show-toplevel`
  prints to stderr, so `out.strip()` is empty and the guard still fires.
  Re-triage if `_run` ever captures stderr into `out`.

## dazzle_claude_config/cli.py @ f75a2c14af23

- M6 (v0.6.5 sweep, `_ai_options`): `backend=steps[0].backend` ->
  `steps[-1].backend`. **equivalent, after the fix the same mutant
  prompted.** Round 1 killed nothing and the mutant pointed at a real
  defect: `aistep.ai_step` reads `opts.backend`, so a plan whose steps
  differ (`--ai claude,deep:lmstudio`) ran the RECIPE on the deep step's
  backend. `merge.run` now hands each step `replace(ai, backend=
  step.backend)`, and after that every reader of `opts.backend` is inside
  `ai_step` and receives the step's own; `aideep` takes `step.backend`
  throughout; `AiOptions.backend` survives only as `plan()`'s pre-plan
  fallback, unused whenever `steps` is set. So no plan can observe the
  field's value, and the mutant cannot be killed -- while the defect it
  found is pinned by
  `test_ai_plan.py::test_each_step_runs_on_its_own_backend_M6` (a guard
  over the pair: it fails only if the step_opts fix AND the first-step
  value are both undone). (2026-09-09, generation mode 1.) Re-triage the
  moment any reader consults `opts.backend` directly again.
