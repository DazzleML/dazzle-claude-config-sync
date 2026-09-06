"""The library's value types: what a backend IS on paper.

A `Spec` is everything needed to build a backend, and it is exactly the
object that gets hashed into a cache key, written into a provenance record
and printed by a health check -- so it holds the NAME of a credential's
environment variable and never the value, and `identity()` is what those
three consumers are allowed to see. A `Request` is what varies per call and
is the same for every transport. A `Response` says what happened with a
word, not a boolean.
"""
from __future__ import annotations

import dataclasses
import json

import pytest

from dazzle_claude_config._vendor.ailib.types import Readiness, Request, Response, Spec


# -- Spec --------------------------------------------------------------------------

def test_a_spec_is_frozen_and_replaceable():
    s = Spec("openai", name="lmstudio", endpoint="http://127.0.0.1:1234/v1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.model = "x"                                   # type: ignore[misc]
    t = s.with_(model="qwen")
    assert t.model == "qwen" and s.model == "" and t.endpoint == s.endpoint


def test_identity_names_what_you_asked_and_never_the_secret(monkeypatch):
    monkeypatch.setenv("SOME_KEY", "hunter2-the-secret")
    s = Spec("openai", endpoint="https://openrouter.ai/api/v1", model="m",
             credential_env="SOME_KEY")
    ident = s.identity()
    assert "hunter2" not in ident and "hunter2" not in repr(s)
    assert "hunter2" not in json.dumps(dataclasses.asdict(s))
    assert "key:SOME_KEY" in ident                      # the NAME is part of who you asked
    assert "openrouter.ai" in ident and "|m|" in ident or "m" in ident


def test_identity_changes_with_the_things_that_change_the_answer():
    base = Spec("openai", endpoint="http://h/v1", model="a")
    assert base.identity() != base.with_(model="b").identity()
    assert base.identity() != base.with_(endpoint="http://other/v1").identity()
    assert base.identity() != base.with_(extra=(("reasoning_effort", "none"),)).identity()
    assert base.identity() != base.with_(transport="cli").identity()


def test_identity_ignores_the_things_that_do_not():
    """A timeout, a hint, an output directory and the executable's resolved
    path change nothing about which model answers -- and a reinstall must
    not flush the cache."""
    base = Spec("cli", command=("claude", "-p", "-"), hint="x")
    assert base.identity() == base.with_(hint="different").identity()
    assert base.identity() == base.with_(candidates=("/somewhere/else/claude",)).identity()
    assert base.identity() == base.with_(env_unset=("A",)).identity()
    assert base.identity() == base.with_(on_prem=True).identity()


def test_identity_of_a_cli_spec_is_the_template_not_the_substitution():
    """The unsubstituted template, so two runs with the same preset share a
    cache even though {model} differs per call... which it does not: the
    model is IN the spec, so it is in the identity too."""
    s = Spec("cli", command=("codex", "exec", "-m", "{model}", "-"), model="o3")
    assert "{model}" in s.identity() and "o3" in s.identity()


def test_extra_is_ordered_in_the_identity():
    a = Spec("openai", extra=(("x", 1), ("y", 2)))
    b = Spec("openai", extra=(("y", 2), ("x", 1)))
    assert a.identity() == b.identity()


# -- Request -----------------------------------------------------------------------

def test_a_request_fingerprint_excludes_the_stream_and_the_timeout():
    import io
    a = Request(prompt="p", schema={"type": "object"})
    b = Request(prompt="p", schema={"type": "object"}, timeout=7, stream_to=io.StringIO())
    assert a.fingerprint() == b.fingerprint()
    assert a.fingerprint() != Request(prompt="q", schema={"type": "object"}).fingerprint()
    assert a.fingerprint() != Request(prompt="p").fingerprint()
    assert a.fingerprint() != Request(prompt="p", schema={"type": "object"}, max_tokens=5).fingerprint()


def test_request_defaults_send_nothing_they_do_not_have_to():
    r = Request(prompt="p")
    assert r.schema is None and r.max_tokens is None and r.stream_to is None
    assert r.temperature == 0 and r.timeout == 120


# -- Response and Readiness ----------------------------------------------------------

def test_a_response_is_a_word_and_ok_is_derived():
    assert Response("answered", text="x").ok is True
    assert Response("deferred", artifact="/p").ok is False
    assert Response("failed", error="no").ok is False
    with pytest.raises(ValueError):
        Response("maybe")


def test_readiness_carries_a_sentence_and_optionally_a_warning():
    r = Readiness(True, "reachable, model m", warning="window is huge")
    assert r.ok and "reachable" in r.reason and r.warning
    assert Readiness(False, "not on PATH").warning == ""
