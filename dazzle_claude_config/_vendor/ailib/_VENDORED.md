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
| `backends/__init__.py` | 1 | d154191a869c6c1930de58dcaa841130dba8b3737687d951887fe4db43c20285 |
| `backends/claude.py` | 155 | 10ff167263b7cd2e21e241daa5c137c262ceefaaf63133c2fb6eb6d580227e76 |
| `backends/codex.py` | 171 | e44b935da2e27e7bce62373b07c827536e857c83a738f75836c0810a4bb793cc |
| `backends/prompt_only.py` | 53 | 613b11217523490ba1f3ffd1acfc7e1716e64a16ee615ed6a4b885d43b8b2479 |

657 lines in six files, as received.

## Changes since the copy

Every file below differs from the fingerprint above, or was written here. One entry each, dated, with why.

- **`backends/lmstudio.py` -- written here, 2026-09-04.** A backend for a local OpenAI-compatible server (LM Studio, Ollama, llama.cpp). The other three backends are CLI-shaped -- an executable on PATH, run as a subprocess -- and this one is HTTP-shaped: availability is a connection rather than a file, the endpoint and model are configuration rather than discovery, and a failure means *the server is not running* rather than *the CLI is not installed*. Every consumer that cares about keeping its text on its own network wants this shape, so it belongs to the library rather than to ccs. Caller-agnostic on purpose: it takes the answer's JSON schema through `set_schema` rather than knowing one, and ccs's merge schema is handed over by `ailib.set_endpoint`. Everything unusual in it is a measured fact about LM Studio, recorded in its docstring.

*(No copied file has been edited yet. When one is, its entry goes here.)*

## Queued improvements -- now unblocked

The old policy deferred these to "upstream first". There is no upstream to go first: they land here, and travel outward with the rest.

1. **Configuration per call.** The contract is `invoke(prompt, verbose, timeout)` with nowhere to pass configuration, so every backend that needs any keeps it in module globals and the caller sets-a-global-then-calls. A proof of concept (`tests/one-offs/thinking/backend-config-per-call/`) put a control arm against today's design under a forced interleave and got total cross-talk -- one caller's request reached the *wrong server*, its own server receiving nothing -- while `invoke(prompt, *, config)` kept two callers apart cleanly. Cost: `lmstudio` 25 lines of 319 touch module state, `prompt_only` 3 of 53, `claude` 0 of 155, `codex` 0 of 171, plus one dispatcher call site at `analyzer.py:213`.
2. **`--model` for codex.** `codex exec` takes `-m/--model`, but its argv is built inside `codex.py`, so ccs's `ai_merge_model` is honoured by `lmstudio` and by `claude` (through `ANTHROPIC_MODEL`, set by the facade) and not by codex, which `ccs doctor` currently warns about rather than pretending otherwise. Configuration per call is where it lands.
3. **Two things the facade holds only because the copy was foreign**: running a CLI backend from a throwaway working directory, so a consumer's own instruction files cannot leak into a prompt; and reading the LAST fenced ```json block from a reply. Both are generic and belong in the library.

Sequencing: these are a slice of their own, after the merge to main and the release. Nothing waiting on ccs needs them.

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

`dazzle_claude_config/ailib.py` -- the only module in ccs that imports anything under `_vendor/`:

- rebinds `analyzer._BACKENDS` to `dazzle_claude_config._vendor.ailib.backends.*` (the vendored file spells them `wtf_windows.lib.ai.backends.*`);
- `backend_names()`, `get_backend(name)`, `check_available(name)`, `model_is_honoured(name)`;
- `invoke(name, prompt, *, verbose, timeout, cwd=None, model=None)` -- runs the backend from a throwaway directory (or `cwd`), restores the caller's directory in `finally`, and is the **single** path by which a model is named: `ANTHROPIC_MODEL` for claude, `configure(model=)` for lmstudio, nothing for codex until item 2 above;
- `cache_key`, `cache_read`, `cache_write`, `CACHE_TTL_SECONDS` re-exported from `analyzer`;
- `set_prompt_dir(path)` for `prompt-only`; `set_endpoint(url)` and `local_describe(model=None)` for `lmstudio`;
- `parse_json_block(text)` -- the last fenced ```json block, parsed; the vendored `parse_response` (section labels) is unused by ccs, as are `analyze()` and `build_prompt()`.
