"""The prompt-file transport: writes the request for a person to carry, and
answers "deferred" -- a third status, so no caller has to read a False as
"it worked, sort of"."""
from __future__ import annotations

from dazzle_claude_config._vendor.ailib.backend import build
from dazzle_claude_config._vendor.ailib.types import Request, Spec


def test_it_writes_the_prompt_and_answers_deferred(tmp_path):
    b = build(Spec("prompt-file", name="prompt-only", endpoint=str(tmp_path / "prompts")))
    assert b.probe().ok
    r = b.invoke(Request(prompt="carry me"))
    assert r.status == "deferred" and r.ok is False
    assert r.artifact and (tmp_path / "prompts").is_dir()
    assert open(r.artifact, encoding="utf-8").read() == "carry me"


def test_two_prompts_in_one_second_do_not_collide(tmp_path):
    b = build(Spec("prompt-file", endpoint=str(tmp_path)))
    a, c = b.invoke(Request(prompt="1")), b.invoke(Request(prompt="2"))
    assert a.artifact != c.artifact


def test_without_a_directory_it_says_so(tmp_path):
    b = build(Spec("prompt-file"))
    assert b.probe().ok is False and "directory" in b.probe().reason
    assert b.invoke(Request(prompt="x")).status == "failed"


def test_nothing_leaves(tmp_path):
    assert "data_stays_on_prem" in build(Spec("prompt-file", endpoint=str(tmp_path))).capabilities
