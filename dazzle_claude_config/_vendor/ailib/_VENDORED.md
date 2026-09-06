# The AI library: our fork of record

## What this directory is

A copy of wtf-windows' `lib/ai`, taken byte-for-byte on 2026-09-03 and **customised here since** -- our own instance of the vendor, in the way a git subtree is. It is not a read-only mirror, and it is no longer required to match its origin byte for byte.

That is a deliberate change of policy, made 2026-09-05. The earlier version of this file locked the copy with a hash table and a test that failed on a changed byte, on the assumption that the copy's job was to stay cheaply re-syncable. The maintainer's correction:

> Our vendored copy is OPEN to improvements, we don't need it to be byte-identical. In fact the entire point is for our version to BECOME the real library. SO if we can improve the library we absolutely should be doing so.

The reasoning behind accepting it, and what replaced the lock, is in `2026-09-05__15-25-29__dev-workflow-process__what-the-ai-library-is.md` (project-private), with a correction in its addendum of the same day. The short version: upstream's `lib/ai` has not changed since we copied it, so there is no divergence to reconcile; the maintainer has said which copy is the one to develop; and the origin **does** have a live caller -- `wtf locked --ai` (`tools/core/locked/locked.py`, a registered tool) imports `analyze` and `check_available` -- which makes wtf-windows a real consumer of the library this tree is becoming, not a reason to freeze the tree. (An earlier version of this paragraph said nothing there called `analyze()`. That came from a search of `src/` that never covered `tools/`; it was wrong, and it was not the reason the policy changed.)

## The guarantee this tree owes

**Purity, not sameness.** What makes a copy adoptable by another project is that it names nothing of its host -- not that it matches a hash. So, enforced by `tests/test_vendored_ailib.py` over **every** file here, copied or authored:

- no import of `dazzle_claude_config`, and no relative import climbing out of `_vendor/ailib`;
- none of ccs's own tokens anywhere in the text;
- the standard library only (`pyproject.toml` keeps `dependencies = []`).

Break any of those and the tree stops being liftable, which is the only property that matters now.

**And honesty.** A file that differs from what we copied must say so in *Changes since the copy* below. The test enforces that too: an edited file with no entry fails. A fork of record is only useful while its record is true, and the failure mode of a fork is a record that quietly rots.

## Origin

| | |
|---|---|
| Repository | `wtf-windows` (local checkout `C:\code\wtf-windows` on plzwork; DazzleML) |
| Path | `src/wtf_windows/lib/ai/` |
| Commit | `a795fe51d552a5fade87c39d6f99ffe2c65fcaaa` -- the last commit touching that directory (2026-03-18); the repository's HEAD at copy time was `a2f993b` (v0.1.7-alpha, 2026-06-10) |
| Copied | 2026-09-03, with the OS (`cp -p`), never retyped |
| Upstream since | unchanged as of 2026-09-05 (`git log a795fe5..HEAD -- src/wtf_windows/lib/ai/` is empty) |

## Copied files, and the fingerprint each arrived with

These hashes record **what we received**, so a reader can tell an edited file from an untouched one and see exactly what the delta is against. They are no longer a lock. sha256 over LF-normalised bytes (`\r\n` -> `\n`), because `claude.py` and `codex.py` are CRLF on disk upstream and git may re-line-end any of them.

| file | lines at copy | sha256 as received |
|---|---|---|
| `__init__.py` | 1 | f9802ac6f4dd911bf77d1a0943356bfb541347bd0212f6259427dfd69758bfa7 |
| `analyzer.py` | 276 | 0f5eb8aacde228553a2f0f7ef6c45130e9008b79286461efb9d84af9884f5424 |

657 lines in six files, as received; two remain. The other four were **removed on 2026-09-05** (U3 of the seam rebuild) once every measured fact they carried had a home and a test in `transports/`. Their fingerprints stay here so the record keeps what was received -- in a separate table, with the date last, so the honesty test does not look for them on disk:

| file | lines at copy | sha256 as received | removed |
|---|---|---|---|
| `backends/__init__.py` | 1 | d154191a869c6c1930de58dcaa841130dba8b3737687d951887fe4db43c20285 | 2026-09-05 |
| `backends/claude.py` | 155 | 10ff167263b7cd2e21e241daa5c137c262ceefaaf63133c2fb6eb6d580227e76 | 2026-09-05 (the env scrub, the `~/.local/bin` candidates and the streaming reader live in `transports/cli.py`) |
| `backends/codex.py` | 171 | e44b935da2e27e7bce62373b07c827536e857c83a738f75836c0810a4bb793cc | 2026-09-05 (the npm/WinGet shim candidates and the `--version` validation live in `transports/cli.py`) |
| `backends/prompt_only.py` | 53 | 613b11217523490ba1f3ffd1acfc7e1716e64a16ee615ed6a4b885d43b8b2479 | 2026-09-05 (`transports/prompt_file.py`) |

## Changes since the copy

Every file below differs from the fingerprint above, or was written here. One entry each, dated, with why.

- **`backends/lmstudio.py` -- written here 2026-09-04, absorbed 2026-09-05.** The first HTTP backend in the house, and the measurements it was built on (LM Studio answers `json_object` with HTTP 400 but honours a strict `json_schema`; `reasoning_effort: "none"` is the only thinking-suppression that reaches the model; an HTTP 200 can carry empty content; `/v1/models` lists what is downloaded while `/api/v0/models`, off the server ROOT, says what is loaded; a client timeout does not cancel server work; throughput is dominated by the context window). All of it now lives in `transports/openai.py`, generalised so that the same code serves LM Studio, Ollama, OpenAI and OpenRouter -- the module-level `configure`/`set_schema` state it kept is gone with it, replaced by the spec. Removed in U3.

- **The object model -- written here, 2026-09-05** (`types.py`, `backend.py`, `cache.py`, `parsers.py`, `transports/__init__.py`, `transports/cli.py`, `transports/openai.py`, `transports/prompt_file.py`). A backend is a frozen `Spec` (transport, endpoint, model, the *name* of a credential variable, an argv template, an answer locator) built into a `Backend` with `probe()` and `invoke(Request)`; three transports, one per way of reaching a model, so local versus remote is a preset's endpoint and key rather than code; a `Response` whose status is a word; `cache.run()` keyed on the backend's own identity so a caller never learns which facts matter for which transport; two generic readers. Replaces the name-keyed `backends/` modules and their module-level state, which the deletions in U3 remove once every measured fact they carried (LM Studio's load-state probe and empty-content guard, claude's environment scrub, codex's shim validation) has a home and a test here. Design: `2026-09-05__16-52-32__dev-workflow-process__the-ai-object-model-one-door-two-consumers.md` (project-private); the POC that earned it is `tests/one-offs/thinking/ai-object-model/`.
- **`analyzer.py` -- edited 2026-09-05, twice.** First, the defect: `analyze(refresh=True)` raised `UnboundLocalError` (the cache key was bound only under `if not refresh`, then read at the write) -- verbatim upstream, where `wtf locked --ai --ai-refresh` crashed; fixed by computing the key once. Then, the same day, `analyze()` and `check_available()` became **thin compatibility wrappers** over the object model: the signature and the four-key result dict are kept for the one live caller (`wtf locked`), the body is `build` -> `probe` -> `cache.run` -> `parsers.sections` with no logic of its own, and a three-name table (`_COMPAT_PRESETS`) maps the origin's `claude` / `codex` / `prompt-only` to specs. Both carry `COMPAT(remove-after: wtf locked migrates to build/run)`; `tests/test_compat_markers.py` holds the inventory. Pinned by `tests/test_analyze_shim.py` with the caller's exact call shape.

## Queued improvements -- delivered 2026-09-05

Written on the morning of 2026-09-05 as a queue for "after the release"; delivered the same afternoon, because the maintainer's review of the seam found the queue was the design. All three landed in the object model above rather than as patches to the old shape:

1. **Configuration per call** -- became *configuration in the object*: a `Spec` is built once, the `Request` carries only what varies per call, and no transport keeps module state. The POC that earned it (`tests/one-offs/thinking/backend-config-per-call/`, then `tests/one-offs/thinking/ai-object-model/`) is retained.
2. **`--model` for codex** -- the preset carries `-m {model}` and the backend's capabilities say so; the facade table that admitted the gap is gone.
3. **The two generic things the facade held** -- the scratch working directory is the `cli` transport's (handed to the child, never `os.chdir`), and the fenced-JSON reader is `parsers.json_block`.

## Destiny

The standalone `dazzle-ailib` -- a perpendicular member of the family depending only on `dazzle-lib` -- with wtf-windows, wtf-restarted and ccs as its consumers (three, which clears the stack map's rule of two).

Note what already exists: **wtf-restarted's copy differs from wtf-windows' in five of the six files** and carries a `prompts/` directory. So there are already three copies of this code in the house and they have already diverged. Reconciling them is that library's first job. What changed on 2026-09-05 is only which copy is the one to reconcile *towards*: this one, because it is the one under active development and the only one with a test suite over it.

Design of record for the original vendoring: `2026-09-01__14-25-05__dev-workflow-process__ccs-merge-ai-the-shared-ai-library-and-the-remap-step.md`, refactor-session addendum. For the policy change: the 2026-09-05 analysis named above.

## Extraction checklist

When the standalone library exists:

1. `pip`-install it and add it to `dependencies` -- gated on the dependency policy (issue #34), and not before a zeromeld adoption has shipped once more with no dependency at all.
2. Point `dazzle_claude_config/ailib.py`'s imports at the library instead of `._vendor.ailib`; the registry rebinding goes away once the library names its own backends.
3. Delete this directory. Nothing else in ccs imports it -- the purity test proves nothing here reaches into ccs, and a grep for `_vendor` outside `ailib.py` and that test proves the reverse.
4. Carry the *Changes since the copy* list into the library's own history, or it is lost.

## Comparing against the origin

```
git -C C:\code\wtf-windows diff a795fe5 -- src/wtf_windows/lib/ai
```

or file by file, line-endings normalised:

```
diff <(sed 's/\r$//' C:/code/wtf-windows/src/wtf_windows/lib/ai/analyzer.py) <(sed 's/\r$//' dazzle_claude_config/_vendor/ailib/analyzer.py)
```

## Facade

`dazzle_claude_config/ailib.py` -- the only module in ccs that imports anything under `_vendor/` (a test in `tests/test_vendored_ailib.py` proves the reverse direction too). Since 2026-09-05 it is the **presets**, not a compatibility layer:

- `PRESETS` -- the named backends a person types after `--ai`, as data over the library's transports: `claude`, `claude-strict`, `codex`, `codex-strict` (transport `cli`, with the argv the live runs proved and, for the strict pair, an answer locator); `lmstudio`, `ollama`, `openai`, `openrouter` (transport `openai`, differing only in endpoint, extras and the name of a credential variable). Local versus remote is an endpoint and a key, never code;
- `names()`, `spec_for(name, *, endpoint, model, api_key_env)`, `build_backend(opts)` -- the person's overrides applied to a preset, and the object the caller talks to;
- re-exports of the library's `build`, `run`, `Request` and `parsers`, so nothing else in ccs imports `_vendor`.

Everything the old facade did to compensate for a foreign copy -- the registry rebinding, the `os.chdir` scratch directory, the `ANTHROPIC_MODEL` route, the per-backend setters, its own JSON reader -- is gone: the transports own those properties now, with tests.
