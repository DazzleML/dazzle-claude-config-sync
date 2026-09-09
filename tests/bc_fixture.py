"""The b()/c() fixture -- the maintainer's own example of a merge git gets
wrong without an error, made concrete (2026-09-09, #64).

    base    a() -> b() -> c(); c returns an int
    ours    Bob changes b():     v = c(x); return v * 2      (assumes an int)
    theirs  Charlie changes c(): returns the tuple (x + 1, x - 1)

`git merge-file --diff3` merges the two cleanly (measured in
tests/one-offs/thinking/deep-merge/probe_local_notools_diff.py: no
markers) and the result is wrong without erroring -- `(x + 1, x - 1) * 2`
is tuple repetition, so a(3) is (4, 2, 4, 2) where an integer was meant.
The control: Charlie returns a plain int, the merge is clean AND right.

Shared by the rung classifier's tests (U2) and the deep golden set (U6),
so the two agree on every byte. `MERGED_BROKEN` is what git's clean
merge produces -- both changes applied to the base -- written out here
rather than computed, so a test needs no git.
"""
from __future__ import annotations

BASE = """def c(x):
    return x + 1


def b(x):
    return c(x)


def a(x):
    return b(x)
"""
OURS = BASE.replace("def b(x):\n    return c(x)\n", "def b(x):\n    v = c(x)\n    return v * 2\n")
THEIRS_BROKEN = BASE.replace("def c(x):\n    return x + 1\n", "def c(x):\n    return (x + 1, x - 1)\n")
THEIRS_FINE = BASE.replace("def c(x):\n    return x + 1\n", "def c(x):\n    return x + 2\n")

#: git's clean merge of OURS and THEIRS_BROKEN: both changes, no markers.
MERGED_BROKEN = THEIRS_BROKEN.replace("def b(x):\n    return c(x)\n", "def b(x):\n    v = c(x)\n    return v * 2\n")
#: git's clean merge of OURS and THEIRS_FINE.
MERGED_FINE = THEIRS_FINE.replace("def b(x):\n    return c(x)\n", "def b(x):\n    v = c(x)\n    return v * 2\n")

#: The hand fix at rung 1: b() adapts to the tuple, nothing else moves.
FIXED_BROKEN = MERGED_BROKEN.replace("    return v * 2\n", "    return (v[0] * 2, v[1] * 2)\n")
#: A fix that reaches outside the changed regions: a() unwraps instead --
#: the same program, but an edit to a function neither side touched.
FIXED_IN_A = MERGED_BROKEN.replace("def a(x):\n    return b(x)\n", "def a(x):\n    t = b(x)\n    return t[0]\n")
