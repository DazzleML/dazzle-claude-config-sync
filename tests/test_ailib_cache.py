"""`run()` -- the cache helper both consumers call.

The key is the backend's own identity plus the request's fingerprint plus
whatever facts the caller adds, so the caller never learns which backend
facts matter for which transport. A hit reproduces the response the
backend gave, marked cached. Nothing is written for a deferred or failed
answer. A refresh skips the read and still writes -- the defect U0 fixed
in the origin's analyze(), pinned here at the primitive.
"""
from __future__ import annotations

import json
import os
import time

import pytest

from dazzle_claude_config._vendor.ailib import cache
from dazzle_claude_config._vendor.ailib.backend import build, register_transport
from dazzle_claude_config._vendor.ailib.types import Readiness, Request, Response, Spec


class FakeTransport:
    def __init__(self):
        self.calls = 0
        self.response = Response("answered", text='{"a": 1}', model_used="fake-1", honoured=("model",))

    def probe(self, spec):
        return Readiness(True, "fake is ready")

    def invoke(self, spec, req):
        self.calls += 1
        return self.response

    def capabilities(self, spec):
        return frozenset({"model"})


@pytest.fixture
def fake(monkeypatch):
    t = FakeTransport()
    register_transport("fake", t)
    yield t
    register_transport("fake", None)


def _run(backend, cache_dir, **kw):
    return cache.run(backend, Request(prompt="p"), cache_dir=cache_dir, tool="t", **kw)


def test_a_live_answer_is_cached_and_the_next_call_is_a_hit(tmp_path, fake):
    b = build(Spec("fake", name="f1", model="m"))
    first = _run(b, tmp_path)
    assert first.ok and first.cached is False and first.key
    files = list(tmp_path.glob("t_f1_*.json"))
    assert len(files) == 1, "file named {tool}_{name}_{key}.json"
    second = _run(b, tmp_path)
    assert second.cached is True and second.cached_at > 0
    assert second.text == first.text and second.model_used == "fake-1" and second.honoured == ("model",)
    assert fake.calls == 1


def test_refresh_re_asks_and_re_writes(tmp_path, fake):
    b = build(Spec("fake", name="f1"))
    _run(b, tmp_path)
    r = _run(b, tmp_path, refresh=True)
    assert fake.calls == 2 and r.cached is False
    assert len(list(tmp_path.glob("t_f1_*.json"))) == 1     # overwritten, not duplicated
    assert _run(b, tmp_path).cached is True


def test_nothing_is_written_for_a_failed_or_deferred_answer(tmp_path, fake):
    b = build(Spec("fake", name="f1"))
    fake.response = Response("failed", error="no")
    assert _run(b, tmp_path).status == "failed"
    fake.response = Response("deferred", artifact="/x")
    assert _run(b, tmp_path).status == "deferred"
    assert not list(tmp_path.glob("*.json"))


def test_the_key_changes_with_identity_request_and_caller_facts(tmp_path, fake):
    a = build(Spec("fake", name="f1", model="m1"))
    b = build(Spec("fake", name="f1", model="m2"))
    req = Request(prompt="p")
    k = cache.cache_key
    assert k(a, req, None, "t") != k(b, req, None, "t")                        # identity
    assert k(a, req, None, "t") != k(a, Request(prompt="q"), None, "t")          # request
    assert k(a, req, {"ours": "sha1"}, "t") != k(a, req, {"ours": "sha2"}, "t")  # caller facts
    assert k(a, req, None, "t") != k(a, req, None, "other-tool")                 # tool
    assert k(a, req, {"x": 1, "y": 2}, "t") == k(a, req, {"y": 2, "x": 1}, "t")  # order-free


def test_the_key_text_names_no_transport_or_preset(tmp_path, fake):
    b = build(Spec("fake", name="lmstudio-ish"))
    key = cache.cache_key(b, Request(prompt="p"), None, "t")
    assert len(key) == 16 and all(c in "0123456789abcdef" for c in key)


def test_a_malformed_cache_file_falls_through_to_the_backend(tmp_path, fake):
    b = build(Spec("fake", name="f1"))
    key = cache.cache_key(b, Request(prompt="p"), None, "t")
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / f"t_f1_{key}.json").write_text("{not json", encoding="utf-8")
    r = _run(b, tmp_path)
    assert r.ok and r.cached is False and fake.calls == 1


def test_an_entry_with_empty_text_is_not_a_hit(tmp_path, fake):
    """Sweep survivor m12: a stored answer with no text is not an answer;
    the backend is asked again rather than an empty 'answered' served."""
    b = build(Spec("fake", name="f1"))
    _run(b, tmp_path)
    (f,) = tmp_path.glob("t_f1_*.json")
    f.write_text(json.dumps({"cached_at": time.time(), "response": {"text": ""}}), encoding="utf-8")
    r = _run(b, tmp_path)
    assert r.cached is False and r.text and fake.calls == 2


def test_an_expired_entry_is_a_miss(tmp_path, fake, monkeypatch):
    b = build(Spec("fake", name="f1"))
    _run(b, tmp_path)
    monkeypatch.setattr(cache, "_now", lambda: time.time() + cache.CACHE_TTL_SECONDS + 1)
    r = _run(b, tmp_path)
    assert r.cached is False and fake.calls == 2


def test_a_write_sweeps_stale_files_under_any_name(tmp_path, fake, monkeypatch):
    """Files under the OLD naming (ai_<backend>_<key>.json) would never be
    looked up again and so never expire; a write sweeps everything stale."""
    old = tmp_path / "ai_claude_deadbeef.json"
    tmp_path.mkdir(exist_ok=True)
    old.write_text(json.dumps({"cached_at": 1.0, "result": {}}), encoding="utf-8")
    fresh = tmp_path / "ai_claude_feedface.json"
    fresh.write_text(json.dumps({"cached_at": time.time(), "result": {}}), encoding="utf-8")
    _run(build(Spec("fake", name="f1")), tmp_path)
    assert not old.exists() and fresh.exists()


def test_the_cache_dir_is_created_on_first_write(tmp_path, fake):
    d = tmp_path / "deep" / "er"
    _run(build(Spec("fake", name="f1")), d)
    assert d.is_dir()
