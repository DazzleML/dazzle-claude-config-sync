# Vendored: the AI analysis library from wtf-windows

## Origin

| | |
|---|---|
| Repository | `wtf-windows` (local checkout `C:\code\wtf-windows` on plzwork; DazzleML) |
| Path | `src/wtf_windows/lib/ai/` |
| Commit | `a795fe51d552a5fade87c39d6f99ffe2c65fcaaa` -- the last commit touching that directory (2026-03-18); the repository's HEAD at copy time was `a2f993b` (v0.1.7-alpha, 2026-06-10) |
| Copied | 2026-09-03, with the OS (`cp -p`), never retyped |

## Status

Verbatim. No file under this directory has been edited since the copy. The one wtf-windows-specific thing in it -- `analyzer.py` lines 32-36 name the backends as `wtf_windows.lib.ai.backends.*` -- is rebound from outside, in `dazzle_claude_config/ailib.py`, which is the only module in ccs that imports anything under `_vendor/`.

## Original files

Hashes are sha256 over the LF-normalised bytes (`\r\n` -> `\n`), because `backends/claude.py` and `backends/codex.py` are CRLF on disk in the source and git may re-line-end any of them on checkout. `tests/test_vendored_ailib.py` recomputes these on every run.

| file | lines | sha256 (LF-normalised) |
|---|---|---|
| `__init__.py` | 1 | f9802ac6f4dd911bf77d1a0943356bfb541347bd0212f6259427dfd69758bfa7 |
| `analyzer.py` | 276 | 0f5eb8aacde228553a2f0f7ef6c45130e9008b79286461efb9d84af9884f5424 |
| `backends/__init__.py` | 1 | d154191a869c6c1930de58dcaa841130dba8b3737687d951887fe4db43c20285 |
| `backends/claude.py` | 155 | 10ff167263b7cd2e21e241daa5c137c262ceefaaf63133c2fb6eb6d580227e76 |
| `backends/codex.py` | 171 | e44b935da2e27e7bce62373b07c827536e857c83a738f75836c0810a4bb793cc |
| `backends/prompt_only.py` | 53 | 613b11217523490ba1f3ffd1acfc7e1716e64a16ee615ed6a4b885d43b8b2479 |

657 lines in six files.

## Local edits

None. Anything ccs needs that the copy does not provide lives in the facade (below). If an edit here ever becomes unavoidable, list it in this section with the design document that required it, and refresh the hash above in the same commit -- the drift test fails otherwise, on purpose.

## Dependencies added

None. `pyproject.toml` keeps `dependencies = []`; the six files use only the standard library.

## Destiny

The standalone `dazzle-ailib` -- a perpendicular member of the family depending only on `dazzle-lib` -- with wtf-windows, wtf-restarted and ccs as its consumers (three, which clears the stack map's rule of two). wtf-restarted's copy differs from wtf-windows' in five of the six files and carries a `prompts/` directory; reconciling the two is that library's first job, not this copy's. ccs must not become a fourth divergent copy: hence "no local edits". Design of record: `2026-09-01__14-25-05__dev-workflow-process__ccs-merge-ai-the-shared-ai-library-and-the-remap-step.md` (project-private), the refactor-session addendum.

## Extraction checklist

When the standalone library exists:

1. `pip`-install it and add it to `dependencies` (this is gated on the dependency policy, issue #34 -- not before the zeromeld adoption ships once more with no dependency).
2. Point the imports in `dazzle_claude_config/ailib.py` at the library instead of `._vendor.ailib`; the rebinding of the registry goes away (the library names its own backends).
3. Delete this directory. Nothing else in ccs imports it -- `tests/test_vendored_ailib.py`'s purity test is the proof that nothing under here reaches into ccs, and a grep for `_vendor` outside `ailib.py` and that test is the proof of the reverse.
4. Keep the facade's additions (neutral working directory, `parse_json_block`) until the library offers them.

## Drift check

To see what the source has changed since the copy:

```
git -C C:\code\wtf-windows diff a795fe5 -- src/wtf_windows/lib/ai
```

or, file by file against the working copy of any wtf-windows checkout:

```
diff <(sed 's/\r$//' C:/code/wtf-windows/src/wtf_windows/lib/ai/analyzer.py) <(sed 's/\r$//' dazzle_claude_config/_vendor/ailib/analyzer.py)
```

Known deltas at copy time, deliberately not carried in: none in the six files. Known upstream divergence: wtf-restarted's copy (see Destiny).

## Facade

`dazzle_claude_config/ailib.py`:

- rebinds `analyzer._BACKENDS` to `dazzle_claude_config._vendor.ailib.backends.*`;
- `backend_names()`, `get_backend(name)`, `check_available(name)`;
- `invoke(name, prompt, *, verbose, timeout, cwd=None)` -- runs the backend from a throwaway directory (or `cwd`) and restores the caller's directory in `finally`; the vendored `invoke` has no such parameter and the CLI backends inherit the process directory;
- `cache_key`, `cache_read`, `cache_write`, `CACHE_TTL_SECONDS` re-exported from `analyzer`;
- `set_prompt_dir(path)` for the `prompt-only` backend;
- `parse_json_block(text)` -- the last fenced ```json block, parsed; the vendored `parse_response` (section labels) is unused by ccs.
