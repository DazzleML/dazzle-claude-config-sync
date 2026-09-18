"""Does `git apply` take the diff the local model actually wrote?

On 2026-09-16 the maintainer pasted the deep step's captured prompt into LM
Studio's chat (qwen3.8-27b-uncensored). The model's final answer was the
golden fix, `return (v[0] * 2, v[1] * 2)`, as a ZERO-CONTEXT hunk:

    @@ -7,1 +7,1 @@
    -    return v * 2
    +    return (v[0] * 2, v[1] * 2)

Its visible reasoning chose zero context on purpose, to avoid blank context
lines whose single leading space a chat or markdown layer might trim. git's
own documentation says `git apply` expects at least one line of context
unless `--unidiff-zero` is passed. This probe writes git's merge of the
founding case and that exact patch into a scratch directory and runs
`git apply --check` under several flag sets, so the no-tools form's apply
call can be judged against a real answer rather than the fixtures' derived
diffs (which difflib writes with three lines of context).

Usage:  python tests/one-offs/thinking/deep-merge/probe_zero_context_apply.py [scratch dir]
Writes only under the scratch dir (default: a fresh temp dir). No model, no git repo.
"""
from __future__ import annotations

import subprocess as sp
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[3]))          # tests/, for bc_fixture
from bc_fixture import MERGED_BROKEN, FIXED_BROKEN  # noqa: E402

# verbatim from the LM Studio export "Tuple Doubling Fix - 2026-09-16 01.52.md"
MODEL_PATCH = """--- a/s.py
+++ b/s.py
@@ -7,1 +7,1 @@
-    return v * 2
+    return (v[0] * 2, v[1] * 2)
"""

# the same edit as the fixtures derive it: three lines of context, the way
# difflib.unified_diff and git itself write hunks
CONTEXT_PATCH = """--- a/s.py
+++ b/s.py
@@ -4,8 +4,8 @@

 def b(x):
     v = c(x)
-    return v * 2
+    return (v[0] * 2, v[1] * 2)


 def a(x):
"""

FLAG_SETS = [
    [],
    ["--unidiff-zero"],
    ["--recount"],
    ["--recount", "--unidiff-zero"],
    ["--ignore-whitespace", "--unidiff-zero"],
]


def main(argv: list[str] | None = None) -> int:
    root = Path(argv[0]) if argv else Path(tempfile.mkdtemp(prefix="ccs-zero-ctx-"))
    root.mkdir(parents=True, exist_ok=True)
    (root / "s.py").write_text(MERGED_BROKEN, encoding="utf-8", newline="\n")
    (root / "model.patch").write_text(MODEL_PATCH, encoding="utf-8", newline="\n")
    (root / "context.patch").write_text(CONTEXT_PATCH, encoding="utf-8", newline="\n")
    print(f"scratch: {root}\n")
    for patch in ("model.patch", "context.patch"):
        for flags in FLAG_SETS:
            r = sp.run(["git", "apply", "--check", "--unsafe-paths", *flags, patch],
                       cwd=root, capture_output=True, text=True, encoding="utf-8")
            verdict = "applies" if r.returncode == 0 else f"REFUSED: {(r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip() else 'rc ' + str(r.returncode)}"
            print(f"{patch:14} git apply --check {' '.join(flags) or '(no flags)':36} -> {verdict}")
        print()
    # and apply the model's patch for real under the flags that took it, to prove the result is the golden text
    r = sp.run(["git", "apply", "--unsafe-paths", "--unidiff-zero", "model.patch"],
               cwd=root, capture_output=True, text=True, encoding="utf-8")
    got = (root / "s.py").read_text(encoding="utf-8")
    print(f"applied model.patch with --unidiff-zero: rc {r.returncode}; "
          f"result {'==' if got == FIXED_BROKEN else '!='} the golden text FIXED_BROKEN")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
