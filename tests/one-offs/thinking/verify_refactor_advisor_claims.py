"""Check the refactor-advisor's falsifiable claims about the AI seam (2026-09-05).

The maintainer's rule: do not take the advisor at face value. Each claim below
is something the design would stand on, and each can be checked in seconds.
Read-only: nothing under the repo is written. Run from the worktree root:

    python tests/one-offs/thinking/verify_refactor_advisor_claims.py

Prints one line per claim: HELD / REFUTED / PARTIAL, with the evidence.
Report: private/claude/2026-09-05__17-05-00__refactor-advisor__the-ai-seam.md
"""
from __future__ import annotations

import hashlib
import importlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
PKG = ROOT / "dazzle_claude_config"
VENDOR = PKG / "_vendor" / "ailib"

results: list[tuple[str, str, str]] = []


def record(claim: str, verdict: str, evidence: str) -> None:
    results.append((claim, verdict, evidence))


# -- row 1: analyze(refresh=True) raises UnboundLocalError ---------------------
def check_row1() -> None:
    from dazzle_claude_config import ailib  # binds the registry to our copy
    from dazzle_claude_config._vendor.ailib import analyzer

    class Stub:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def invoke(prompt, verbose=False, timeout=120):
            return True, "## What Happened\nx\n## Why\ny\n## What To Do\nz\n## Confidence\nhigh"

    saved = dict(analyzer._BACKENDS)
    analyzer._BACKENDS["stub"] = "dazzle_claude_config._vendor.ailib.backends.claude"
    orig_get = analyzer.get_backend
    analyzer.get_backend = lambda name: Stub if name == "stub" else orig_get(name)
    try:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            kw = dict(results={"k": "v"}, fingerprint_fn=lambda r: r,
                      prompt_path=None, cache_dir=Path(td), tool_name="verify",
                      backend_name="stub", refresh=True)
            # build_prompt needs a template; give it one
            tpl = Path(td) / "t.md"
            tpl.write_text("{results}", encoding="utf-8")
            kw["prompt_path"] = tpl
            try:
                analyzer.analyze(**kw)
                record("row 1: analyze(refresh=True) crashes", "REFUTED",
                       "analyze(refresh=True) returned without raising")
            except UnboundLocalError as e:
                record("row 1: analyze(refresh=True) crashes", "HELD", f"UnboundLocalError: {e}")
            except TypeError as e:
                record("row 1: analyze(refresh=True) crashes", "PARTIAL",
                       f"signature differs from the probe's guess: {e}")
    finally:
        analyzer.get_backend = orig_get
        analyzer._BACKENDS.clear()
        analyzer._BACKENDS.update(saved)

    # and: is our analyzer.py byte-identical to the origin's (LF-normalised)?
    origin = Path(r"C:\code\wtf-windows\src\wtf_windows\lib\ai\analyzer.py")
    if origin.is_file():
        a = (VENDOR / "analyzer.py").read_bytes().replace(b"\r\n", b"\n")
        b = origin.read_bytes().replace(b"\r\n", b"\n")
        record("row 1b: our analyzer.py == origin's (so the crash is upstream too)",
               "HELD" if a == b else "REFUTED",
               "identical after LF normalisation" if a == b else "differs")


# -- row 2: doctor NameError when the vendored copy is broken and a model is set
def check_row2() -> None:
    src = (PKG / "cli.py").read_text(encoding="utf-8").splitlines()
    # find the doctor AI block: the try that imports the facade, its except, and
    # the model_is_honoured line after it
    try_i = next(i for i, l in enumerate(src) if "from . import ailib as _ailib" in l)
    exc_i = next(i for i in range(try_i, len(src)) if src[i].lstrip().startswith("except Exception as e:") and "vendored" in src[i])
    mih_i = next(i for i in range(try_i, len(src)) if "model_is_honoured(_backend)" in src[i])
    # indentation: is the model_is_honoured line inside the try body?
    def indent(s: str) -> int:
        return len(s) - len(s.lstrip())
    try_body_indent = indent(src[try_i])
    outside = indent(src[mih_i]) < try_body_indent
    record("row 2: doctor's model_is_honoured(_backend) sits OUTSIDE the try/except",
           "HELD" if outside else "REFUTED",
           f"try body indent {try_body_indent}, except at line {exc_i+1}, "
           f"model_is_honoured at line {mih_i+1} indent {indent(src[mih_i])}")
    # and _backend is bound only inside the try?
    bind_i = [i for i in range(try_i, mih_i) if re.search(r"^\s*_backend\s*=", src[i])]
    inside_try = all(indent(src[i]) > try_body_indent for i in bind_i)
    record("row 2b: _backend is bound only inside the try (so NameError is reachable)",
           "HELD" if bind_i and inside_try else "REFUTED",
           f"bindings at lines {[i+1 for i in bind_i]}")


# -- row 4: availability is position-dependent in a per-file loop ---------------
def check_row4() -> None:
    from dazzle_claude_config._vendor.ailib.backends import lmstudio as lm
    saved = (lm._endpoint, lm._model, lm._schema)
    orig_models, orig_loaded = lm.models, lm.loaded_models
    try:
        lm.models = lambda: ["model-A", "model-B"]
        lm.loaded_models = lambda: ["model-A"]
        lm.configure(endpoint="http://127.0.0.1:1", model=None)
        # file 1: caller checks availability (no model pinned), then invokes with
        # a model, which the facade would do via configure(model=...)
        avail_1 = lm.is_available()
        lm.configure(model="model-B")           # what ailib.invoke(model=) does
        # file 2: the same availability check, same inputs from the caller's view
        avail_2 = lm.is_available()
        record("row 4: is_available() differs by position after invoke(model=) leaked",
               "HELD" if avail_1 and not avail_2 else "REFUTED",
               f"file 1 available={avail_1}, file 2 available={avail_2} (same caller inputs)")
    finally:
        lm.models, lm.loaded_models = orig_models, orig_loaded
        lm._endpoint, lm._model, lm._schema = saved


# -- row 7: no auth header anywhere in the vendored tree ------------------------
def check_row7() -> None:
    hits = []
    for p in VENDOR.rglob("*.py"):
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if re.search(r"Authorization|Bearer|api_key|API_KEY", line):
                hits.append(f"{p.relative_to(VENDOR)}:{n}")
    record("row 7: zero auth-header / api-key handling in the vendored tree",
           "HELD" if not hits else "REFUTED", "no hits" if not hits else ", ".join(hits))


# -- row 11: ccs never invokes prompt-only; set_prompt_dir has no prod caller ---
def check_row11() -> None:
    prod_callers = []
    for p in PKG.rglob("*.py"):
        if "_vendor" in p.parts:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            if "set_prompt_dir(" in line and not line.lstrip().startswith("def "):
                prod_callers.append(f"{p.relative_to(PKG)}:{n}")
    record("row 11: set_prompt_dir has no production caller",
           "HELD" if not prod_callers else "REFUTED",
           "none" if not prod_callers else ", ".join(prod_callers))
    # aistep returns before any backend when prompt-only
    src = (PKG / "aistep.py").read_text(encoding="utf-8")
    m = re.search(r"if opts\.backend == ailib\.PROMPT_ONLY:(.*?)\n\s*return out", src, re.S)
    record("row 11b: aistep returns for prompt-only before reaching a backend",
           "HELD" if m and "invoke(" not in m.group(1) else "REFUTED",
           "branch found, no invoke inside it" if m else "branch not found by pattern")


# -- row 13: the caller knows the backend's identity in 7 places ----------------
def check_row13() -> None:
    where = []
    for name in ("aistep.py", "cli.py"):
        for n, line in enumerate((PKG / name).read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\bLMSTUDIO\b|== ?['\"]lmstudio['\"]|PROMPT_ONLY\b", line) and not line.lstrip().startswith("#"):
                if "import" in line or "LMSTUDIO =" in line or "PROMPT_ONLY =" in line:
                    continue
                where.append(f"{name}:{n}")
    record("row 13: backend-identity branches in aistep.py + cli.py",
           "HELD" if len(where) == 7 else "PARTIAL",
           f"{len(where)} found: {', '.join(where)}")


# -- row 17: the two wtf-restarted copies are byte-identical --------------------
def check_row17() -> None:
    a = Path(r"C:\code\wtf-restarted\wtf_restarted\ai")
    b = Path(r"C:\code\wtf-windows\tools\core\restarted\wtf_restarted\ai")
    if not (a.is_dir() and b.is_dir()):
        record("row 17: wtf-restarted copies byte-identical", "PARTIAL", f"missing: {a if not a.is_dir() else b}")
        return
    def digest(d: Path) -> dict[str, str]:
        return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                for p in sorted(d.rglob("*.py")) if "__pycache__" not in p.parts}
    da, db = digest(a), digest(b)
    same = da == db
    record("row 17: wtf-restarted copies byte-identical (LF-normalised)",
           "HELD" if same else "REFUTED",
           f"{len(da)} files each" if same else f"differ: {sorted(set(da.items()) ^ set(db.items()))[:3]}")


# -- row 6: how much of lmstudio.py is LM-Studio-specific -----------------------
def check_row6() -> None:
    src = (VENDOR / "backends" / "lmstudio.py").read_text(encoding="utf-8").splitlines()
    total = len(src)
    specific_fns = {"_get_native", "_native_records", "loaded_models", "context_length", "context_is_roomy"}
    # count lines of those function bodies
    count = 0
    cur = None
    for line in src:
        m = re.match(r"def (\w+)\(", line)
        if m:
            cur = m.group(1)
        if cur in specific_fns and line.strip():
            count += 1
    count += sum(1 for l in src if "reasoning_effort" in l or "DEFAULT_ENDPOINT =" in l)
    record("row 6: LM-Studio-specific share of lmstudio.py",
           "HELD" if count <= 0.25 * total else "PARTIAL",
           f"~{count} of {total} lines ({100*count//total}%) in {sorted(specific_fns)} + 2 constants")


def main() -> int:
    for fn in (check_row1, check_row2, check_row4, check_row7, check_row11, check_row13, check_row17, check_row6):
        try:
            fn()
        except Exception as e:  # a probe that breaks is itself a finding
            record(fn.__name__, "PARTIAL", f"probe raised {type(e).__name__}: {e}")
    width = max(len(c) for c, _, _ in results)
    for claim, verdict, evidence in results:
        print(f"{verdict:8} {claim.ljust(width)}  -- {evidence}")
    held = sum(1 for _, v, _ in results if v == "HELD")
    print(f"\n{held} HELD / {sum(1 for _, v, _ in results if v == 'REFUTED')} REFUTED / "
          f"{sum(1 for _, v, _ in results if v == 'PARTIAL')} PARTIAL of {len(results)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
