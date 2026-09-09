"""The `openai` transport: one adapter for every OpenAI-compatible server --
LM Studio and Ollama on this machine, OpenAI, OpenRouter and the rest over
the wire. Local versus remote is the endpoint and whether a credential is
named; the code is the same.

Against a real socket, not a mock (the reasons are in the file this was
ported from, tests/test_backend_lmstudio.py, retired in U3): a mocked
`urlopen` proves only that we can call our own code. The fake server is
stdlib `http.server` on an ephemeral port, records what it was sent, and
can demand a bearer token -- which is how a hosted provider behaves.

Every measured hazard the lmstudio backend was built around is kept, as a
test: an unloaded model that would JIT-load gigabytes, an HTTP 200 whose
content is empty, a server that was never started, a window far larger
than the job. What is new: a keyed remote, the credential never leaking into
the identity, and two backends alive at once without touching each other.
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from dazzle_claude_config._vendor.ailib.types import Request, Spec
from dazzle_claude_config._vendor.ailib.backend import build

ANSWER = {"hunks": [{"hunk": 1, "lines": ["T1"], "rules": [], "rationale": "upstream"}]}

#: A library-local schema. The transport enforces a shape it is GIVEN; the
#: merge schema is ccs's and reaches it through Request.schema in U2's tests.
SCHEMA = {
    "type": "object",
    "properties": {"hunks": {"type": "array", "items": {
        "type": "object",
        "properties": {"hunk": {"type": "integer"}, "lines": {"type": "array"},
                       "rules": {"type": "array"}, "rationale": {"type": "string"}},
        "required": ["hunk", "lines", "rules", "rationale"],
        "additionalProperties": False}}},
    "required": ["hunks"], "additionalProperties": False,
}


class _Fake:
    """A stand-in LM Studio, shaped like the real one -- and, with a token,
    a stand-in hosted provider.

    The two model listings are DIFFERENT on purpose, because the real server
    is: ``/v1/models`` names everything downloaded, and only LM Studio's own
    ``/api/v0/models`` carries the ``state`` that says what is in memory.
    `native` turns that second endpoint off, which is how an Ollama, a
    llama.cpp, or a hosted endpoint behaves.
    """
    models = ["qwen/qwen3.8-35b", "some/other-model-on-disk"]
    loaded = ["qwen/qwen3.8-35b"]
    context = 16384
    max_context = 262144
    native = True
    content = json.dumps(ANSWER)
    status = 200
    token: str | None = None          # when set, every request must carry it
    sent: dict | None = None
    seen_auth: str | None = None
    requests: int = 0


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):            # keep the test output clean
        pass

    def _json(self, body, status=200):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _auth_ok(self):
        _Fake.seen_auth = self.headers.get("Authorization")
        return _Fake.token is None or _Fake.seen_auth == f"Bearer {_Fake.token}"

    def do_GET(self):
        _Fake.requests += 1
        if not self._auth_ok():
            return self._json({"error": {"message": "unauthorized"}}, 401)
        if self.path.startswith("/api/v0/models"):
            if not _Fake.native:
                return self._json({"error": "not found"}, 404)
            return self._json({"data": [
                {"id": m, "state": "loaded" if m in _Fake.loaded else "not-loaded",
                 "loaded_context_length": _Fake.context if m in _Fake.loaded else None,
                 "max_context_length": _Fake.max_context}
                for m in _Fake.models]})
        if self.path.endswith("/v1/models"):
            return self._json({"data": [{"id": m} for m in _Fake.models]})
        self._json({"error": "no"}, 404)

    def do_POST(self):
        _Fake.requests += 1
        n = int(self.headers.get("Content-Length", 0))
        _Fake.sent = json.loads(self.rfile.read(n).decode())
        if not self._auth_ok():
            return self._json({"error": {"message": "unauthorized"}}, 401)
        if _Fake.status != 200:
            return self._json({"error": {"message": "response_format not supported"}}, _Fake.status)
        self._json({"model": _Fake.sent.get("model"),
                    "choices": [{"message": {"content": _Fake.content}}]})


@pytest.fixture
def server():
    _Fake.models = ["qwen/qwen3.8-35b", "some/other-model-on-disk"]
    _Fake.loaded = ["qwen/qwen3.8-35b"]
    _Fake.context = 16384
    _Fake.max_context = 262144
    _Fake.native = True
    _Fake.content = json.dumps(ANSWER)
    _Fake.status = 200
    _Fake.token = None
    _Fake.sent = None
    _Fake.seen_auth = None
    _Fake.requests = 0
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    srv.url = f"http://127.0.0.1:{srv.server_port}/v1"
    yield srv
    srv.shutdown()
    srv.server_close()


def _spec(url, model="", **kw):
    """The lmstudio preset's shape, without being the preset: the transport
    is told the endpoint, and `reasoning_effort` rides in `extra`."""
    return Spec("openai_compat", name="local", endpoint=url, model=model,
                extra=(("reasoning_effort", "none"),), **kw)


def _ask(backend, **kw):
    return backend.invoke(Request(prompt="resolve this", schema=SCHEMA, timeout=10, **kw))


# -- the answer ------------------------------------------------------------------

def test_a_loaded_model_answers_and_the_answer_comes_back(server):
    b = build(_spec(server.url))
    assert b.probe().ok is True
    r = _ask(b)
    assert r.ok and r.status == "answered"
    assert json.loads(r.text) == ANSWER
    assert r.model_used == "qwen/qwen3.8-35b"
    assert "schema" in r.honoured and "model" in r.honoured


def test_the_request_asks_for_a_strict_schema_not_a_json_object(server):
    """The measured fact the lmstudio backend existed around: LM Studio
    answers `json_object` with HTTP 400, while `json_schema` + strict works."""
    _ask(build(_spec(server.url)))
    fmt = _Fake.sent["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    item = fmt["json_schema"]["schema"]["properties"]["hunks"]["items"]
    assert set(item["required"]) == {"hunk", "lines", "rules", "rationale"}
    assert item["additionalProperties"] is False
    assert _Fake.sent["reasoning_effort"] == "none"    # from Spec.extra, not the transport
    assert _Fake.sent["stream"] is False
    assert _Fake.sent["temperature"] == 0
    assert "max_tokens" not in _Fake.sent               # None means not sent


def test_no_schema_means_no_response_format_and_schema_is_not_honoured(server):
    r = build(_spec(server.url)).invoke(Request(prompt="say hi", timeout=10))
    assert r.ok and "response_format" not in _Fake.sent
    assert "schema" not in r.honoured


def test_max_tokens_is_sent_when_given(server):
    _ask(build(_spec(server.url)), max_tokens=2048)
    assert _Fake.sent["max_tokens"] == 2048


# -- the model roster ------------------------------------------------------------

def test_a_downloaded_but_unloaded_model_is_refused_before_anything_is_sent(server):
    """`some/other-model-on-disk` IS in /v1/models -- downloaded -- and naming
    it would make LM Studio load it from disk. Only the load state says so,
    and nothing is POSTed."""
    b = build(_spec(server.url, model="some/other-model-on-disk"))
    ready = b.probe()
    assert ready.ok is False
    assert "is not loaded" in ready.reason and "qwen/qwen3.8-35b" in ready.reason
    assert "load it from disk" in ready.reason
    r = _ask(b)
    assert r.status == "failed" and "is not loaded" in r.error
    assert _Fake.sent is None                          # never reached the completion


def test_with_no_model_pinned_the_LOADED_one_is_chosen_not_the_first_listed(server):
    _Fake.models = ["some/other-model-on-disk", "qwen/qwen3.8-35b"]   # loaded one second
    r = _ask(build(_spec(server.url)))
    assert r.ok and _Fake.sent["model"] == "qwen/qwen3.8-35b"


def test_a_server_without_the_native_api_still_works(server):
    """Ollama, llama.cpp and every hosted provider speak the OpenAI surface
    and have no load state. "Cannot say" is a third value, never "nothing"."""
    _Fake.native = False
    b = build(_spec(server.url))
    assert b.probe().ok is True
    assert _ask(b).ok


def test_a_pinned_model_is_refused_when_the_server_says_NOTHING_is_loaded(server):
    """The guard reads `live is not None`, not `live`: an EMPTY loaded list is
    the server saying "I have nothing in memory" -- a definite answer."""
    _Fake.loaded = []
    b = build(_spec(server.url, model="qwen/qwen3.8-35b"))
    r = _ask(b)
    assert r.status == "failed"
    assert "is not loaded" in r.error and "loaded: none" in r.error, r.error
    assert _Fake.sent is None


def test_with_nothing_loaded_and_no_pin_it_refuses_rather_than_choosing_one(server):
    _Fake.loaded = []
    r = _ask(build(_spec(server.url)))
    assert r.status == "failed"
    assert "no model loaded" in r.error and "takes minutes" in r.error, r.error
    assert _Fake.sent is None


def test_the_first_loaded_model_is_chosen_deterministically(server):
    _Fake.models = ["a/first", "b/second"]
    _Fake.loaded = ["a/first", "b/second"]
    r = _ask(build(_spec(server.url)))
    assert r.ok and _Fake.sent["model"] == "a/first"


def test_a_pinned_model_that_a_no_state_server_does_not_list_is_refused(server):
    _Fake.native = False
    b = build(_spec(server.url, model="nowhere/model"))
    ready = b.probe()
    assert ready.ok is False and "is not on" in ready.reason and "qwen/qwen3.8-35b" in ready.reason


# -- the context window ----------------------------------------------------------

def test_an_oversized_context_window_is_a_warning_not_a_refusal(server):
    """A 197,120-token window on a 32 GB card: reachable, so not an error --
    but a person deserves to know before they wait minutes."""
    _Fake.context = 197120
    ready = build(_spec(server.url)).probe()
    assert ready.ok is True
    assert "197,120-token context" in ready.warning and "16k-32k" in ready.warning
    _Fake.context = 16384
    ready = build(_spec(server.url)).probe()
    assert ready.warning == "" and "16,384-token context" in ready.reason


def test_the_window_warning_is_about_exceeding_the_threshold_not_meeting_it(server):
    from dazzle_claude_config._vendor.ailib.transports import openai_compat as t
    _Fake.context = t.ROOMY_CONTEXT
    assert build(_spec(server.url)).probe().warning == ""
    _Fake.context = t.ROOMY_CONTEXT + 1
    assert build(_spec(server.url)).probe().warning != ""


def test_the_window_reported_is_the_one_LOADED_not_the_models_maximum(server):
    _Fake.context = 8192
    _Fake.max_context = 262144
    ready = build(_spec(server.url)).probe()
    assert "8,192-token context" in ready.reason and ready.warning == ""


# -- failures with a sentence ----------------------------------------------------

def test_empty_content_on_http_200_is_a_failure_not_an_empty_answer(server):
    _Fake.content = "   "
    r = _ask(build(_spec(server.url)))
    assert r.status == "failed" and "empty content" in r.error


def test_an_http_error_carries_the_servers_own_words_and_is_not_retried(server):
    _Fake.status = 400
    r = _ask(build(_spec(server.url)))
    assert r.status == "failed" and "HTTP 400" in r.error and "response_format" in r.error
    assert _Fake.requests == 2 + 1      # the probe's two listings, then ONE post -- no retry


def test_a_server_that_is_not_running_says_so_and_says_what_to_start():
    """The most likely failure by far: the app is open, the server was never
    started. The hint is the PRESET's (LM Studio's Developer tab), appended
    to a sentence the transport owns."""
    b = build(_spec("http://127.0.0.1:1/v1", hint="in LM Studio: the Developer tab"))
    ready = b.probe()
    assert ready.ok is False
    assert "no model server" in ready.reason and "start the local server" in ready.reason
    assert "Developer tab" in ready.reason
    r = b.invoke(Request(prompt="x", timeout=2))
    assert r.status == "failed" and "no model server" in r.error


def test_without_a_hint_the_sentence_stands_on_its_own():
    ready = build(_spec("http://127.0.0.1:1/v1")).probe()
    assert "no model server" in ready.reason and "Developer" not in ready.reason


# -- readiness describes ----------------------------------------------------------

def test_probe_names_the_endpoint_and_what_is_loaded(server):
    ready = build(_spec(server.url)).probe()
    assert ready.ok and "reachable" in ready.reason and "qwen/qwen3.8-35b" in ready.reason
    assert "/v1" in ready.reason


# -- local versus remote is configuration ----------------------------------------

def test_a_keyed_remote_is_reached_with_a_bearer_and_the_secret_never_leaks(server, monkeypatch):
    _Fake.token = "s3cr3t-value"
    _Fake.native = False                               # a hosted provider has no load state
    monkeypatch.setenv("POC_KEY", "s3cr3t-value")
    spec = Spec("openai_compat", name="remote", endpoint=server.url, model="qwen/qwen3.8-35b",
                credential_env="POC_KEY")
    b = build(spec)
    assert b.probe().ok is True
    r = _ask(b)
    assert r.ok and _Fake.seen_auth == "Bearer s3cr3t-value"
    for where, text in (("identity", b.identity), ("repr", repr(spec)), ("spec", json.dumps(spec.__dict__))):
        assert "s3cr3t" not in text, where
    assert "key:POC_KEY" in b.identity                 # the NAME is part of who you asked


def test_a_keyed_remote_without_the_key_in_the_environment_probes_to_a_sentence(server, monkeypatch):
    _Fake.token = "s3cr3t-value"
    monkeypatch.delenv("POC_KEY", raising=False)
    ready = build(Spec("openai_compat", endpoint=server.url, credential_env="POC_KEY")).probe()
    assert ready.ok is False
    assert "POC_KEY" in ready.reason and "not set" in ready.reason


# -- the credential from a file (K5, 2026-09-09) -----------------------------------
#
# The library's order is fixed: a file named on purpose, then the environment,
# then fallback files. The value is read at request time, put in one header,
# and appears in no identity, sentence or repr. Each test below asserts what
# the FAKE SERVER saw (`_Fake.seen_auth`), never prints a value.

def _keyfile(tmp_path, name="openrouter.env", text="POC_KEY=from-the-file\n"):
    p = tmp_path / "keys" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _remote(url, **kw):
    return Spec("openai_compat", name="remote", endpoint=url, model="qwen/qwen3.8-35b",
                credential_env="POC_KEY", **kw)


def test_a_file_named_on_purpose_wins_over_the_environment(server, tmp_path, monkeypatch):
    _Fake.token = "from-the-file"
    _Fake.native = False
    monkeypatch.setenv("POC_KEY", "from-the-environment")
    kf = _keyfile(tmp_path)
    b = build(_remote(server.url, credential_file=str(kf)))
    assert b.probe().ok is True
    assert _ask(b).ok and _Fake.seen_auth == "Bearer from-the-file"


def test_a_fallback_file_is_read_only_when_the_environment_is_empty(server, tmp_path, monkeypatch):
    kf = _keyfile(tmp_path)
    spec = _remote(server.url, credential_fallbacks=(str(kf),))
    _Fake.native = False
    # the environment has the key: the fallback is not consulted
    _Fake.token = "from-the-environment"
    monkeypatch.setenv("POC_KEY", "from-the-environment")
    assert _ask(build(spec)).ok and _Fake.seen_auth == "Bearer from-the-environment"
    # the environment is empty: the fallback supplies it
    _Fake.token = "from-the-file"
    monkeypatch.delenv("POC_KEY")
    assert _ask(build(spec)).ok and _Fake.seen_auth == "Bearer from-the-file"


def test_the_first_fallback_that_has_the_line_wins(server, tmp_path, monkeypatch):
    _Fake.token = "second"
    _Fake.native = False
    monkeypatch.delenv("POC_KEY", raising=False)
    first = _keyfile(tmp_path, "first.env", "OTHER_KEY=not-this-one\n")
    second = _keyfile(tmp_path, "second.env", "POC_KEY=second\n")
    b = build(_remote(server.url, credential_fallbacks=(str(first), str(second))))
    assert _ask(b).ok and _Fake.seen_auth == "Bearer second"


def test_the_missing_key_sentence_names_the_variable_and_every_file(server, tmp_path, monkeypatch):
    """A person who sees this knows where to put the key: the variable, the
    file that is not there, and the file that is there without the line."""
    monkeypatch.delenv("POC_KEY", raising=False)
    absent = tmp_path / "keys" / "openrouter.env"
    present = _keyfile(tmp_path, "other.env", "SOMETHING_ELSE=x\n")
    ready = build(_remote(server.url, credential_file=str(present),
                          credential_fallbacks=(str(absent),))).probe()
    assert ready.ok is False
    assert "POC_KEY" in ready.reason and "not set" in ready.reason          # what the doctor test pins
    assert str(absent) in ready.reason and "does not exist" in ready.reason
    assert str(present) in ready.reason and "has no POC_KEY line" in ready.reason
    assert "one of them" in ready.reason
    assert _Fake.requests == 0                                              # refused before any request


def test_without_any_file_the_missing_key_sentence_is_unchanged(server, monkeypatch):
    monkeypatch.delenv("POC_KEY", raising=False)
    ready = build(_remote(server.url)).probe()
    assert ready.reason == "POC_KEY is not set in the environment -- remote needs a key there"


def test_the_file_value_never_leaks_and_the_file_is_named_in_the_identity(server, tmp_path, monkeypatch):
    _Fake.token = "s3cr3t-from-file"
    _Fake.native = False
    monkeypatch.delenv("POC_KEY", raising=False)
    kf = _keyfile(tmp_path, text="POC_KEY=s3cr3t-from-file\n")
    spec = _remote(server.url, credential_fallbacks=(str(kf),))
    b = build(spec)
    ready = b.probe()
    assert ready.ok is True and _ask(b).ok
    for where, text in (("identity", b.identity), ("repr", repr(spec)),
                        ("spec", json.dumps(spec.__dict__)), ("reason", ready.reason),
                        ("warning", ready.warning)):
        assert "s3cr3t" not in text, where
    assert "keyfile:openrouter.env" in b.identity
    assert "key:POC_KEY" in b.identity


def test_probe_says_where_the_key_came_from(server, tmp_path, monkeypatch):
    _Fake.native = False
    _Fake.token = "v"
    monkeypatch.setenv("POC_KEY", "v")
    assert "key from POC_KEY" in build(_remote(server.url)).probe().reason
    monkeypatch.delenv("POC_KEY")
    kf = _keyfile(tmp_path, text="POC_KEY=v\n")
    reason = build(_remote(server.url, credential_fallbacks=(str(kf),))).probe().reason
    assert f"key from {kf}" in reason and "v\n" not in reason
    # a local server with no credential says nothing about a key
    _Fake.token = None
    assert "key from" not in build(_spec(server.url)).probe().reason


@pytest.mark.parametrize("text, expected", [
    ("POC_KEY=plain\n", "plain"),
    ("POC_KEY=crlf\r\n", "crlf"),                                   # CRLF
    ("﻿POC_KEY=bom\n", "bom"),                                 # a BOM from a Windows editor
    ('POC_KEY="double quoted"\n', "double quoted"),
    ("POC_KEY='single quoted'\n", "single quoted"),
    ("export POC_KEY=exported\n", "exported"),                      # a sourceable file
    ("# the key\n\nOTHER=x\nPOC_KEY = spaced \n", "spaced"),         # comments, blanks, other lines, spaces
    ("bare-value-only\n", "bare-value-only"),                       # one line, no '=': the value itself
    ("# a comment\nbare-with-comment\n", "bare-with-comment"),
    ("POC_KEY=\n", ""),                                             # an empty value is absent
    ('POC_KEY=""\n', ""),                                           # ...and so is an empty quoted one (survivor M15)
    ("POC_KEY=''\n", ""),
    ("OTHER=x\nANOTHER=y\n", ""),                                   # several lines, none the name: no guess
    ("first-bare\nsecond-bare\n", ""),                              # two bare lines: no guess either (survivor M16)
    ("", ""),
])
def test_the_key_file_formats_that_read(tmp_path, text, expected):
    from dazzle_claude_config._vendor.ailib.transports.openai_compat import _read_key_file
    p = tmp_path / "k.env"
    p.write_bytes(text.encode("utf-8"))
    assert _read_key_file(str(p), "POC_KEY") == expected


def test_a_missing_or_oversized_key_file_reads_as_nothing(tmp_path):
    from dazzle_claude_config._vendor.ailib.transports import openai_compat as t
    assert t._read_key_file(str(tmp_path / "nope.env"), "POC_KEY") == ""
    big = tmp_path / "big.env"
    big.write_text("#" * (t.KEY_FILE_CAP + 10) + "\nPOC_KEY=after-the-cap\n", encoding="utf-8")
    assert t._read_key_file(str(big), "POC_KEY") == ""              # not read past the cap


def test_a_loose_mode_is_group_or_other_bits():
    from dazzle_claude_config._vendor.ailib.transports.openai_compat import _loose_mode
    assert _loose_mode(0o600) is False and _loose_mode(0o400) is False
    assert _loose_mode(0o640) is True and _loose_mode(0o644) is True and _loose_mode(0o604) is True


@pytest.mark.skipif(os.name != "posix", reason="a mode is a POSIX thing; Windows ACLs are not one")
def test_on_posix_a_readable_by_others_key_file_is_a_warning(server, tmp_path, monkeypatch):
    _Fake.native = False
    _Fake.token = "v"
    monkeypatch.delenv("POC_KEY", raising=False)
    kf = _keyfile(tmp_path, text="POC_KEY=v\n")
    kf.chmod(0o644)
    ready = build(_remote(server.url, credential_fallbacks=(str(kf),))).probe()
    assert ready.ok and "readable by others" in ready.warning and "chmod 600" in ready.warning
    kf.chmod(0o600)
    assert build(_remote(server.url, credential_fallbacks=(str(kf),))).probe().warning == ""


def test_the_same_transport_serves_local_and_remote_with_different_specs(server, monkeypatch):
    """One code path; two specs. The point of the taxonomy."""
    _Fake.token = None
    local = build(_spec(server.url))
    assert local.probe().ok
    _Fake.token = "k"
    monkeypatch.setenv("K", "k")
    remote = build(Spec("openai_compat", endpoint=server.url, model="qwen/qwen3.8-35b", credential_env="K"))
    assert remote.probe().ok
    assert type(local._transport) is type(remote._transport)


def test_on_prem_is_derived_from_the_endpoint_when_the_preset_does_not_say(server):
    assert "data_stays_on_prem" in build(_spec(server.url)).capabilities          # 127.0.0.1
    hosted = build(Spec("openai_compat", endpoint="https://openrouter.ai/api/v1", credential_env="X"))
    assert "data_stays_on_prem" not in hosted.capabilities
    lan = build(Spec("openai_compat", endpoint="http://192.168.1.5:1234/v1"))
    assert "data_stays_on_prem" in lan.capabilities
    said = build(Spec("openai_compat", endpoint="https://example.com/v1", on_prem=True))
    assert "data_stays_on_prem" in said.capabilities                                # the preset's word wins
    # ...in BOTH directions: a loopback endpoint the preset declares off-prem
    # (a tunnel to somewhere else, say) must not be promoted by the heuristic.
    # Sweep survivor m2 (2026-09-05): `on_prem or derived` would have.
    denied = build(Spec("openai_compat", endpoint=server.url, on_prem=False))
    assert "data_stays_on_prem" not in denied.capabilities


def test_endpoint_is_on_prem_is_three_valued():
    """Sweep survivor m1: no host at all is "cannot say", not "off-prem"."""
    from dazzle_claude_config._vendor.ailib.transports.openai_compat import endpoint_is_on_prem
    assert endpoint_is_on_prem("") is None
    assert endpoint_is_on_prem("not a url") is None
    assert endpoint_is_on_prem("http://127.0.0.1:1234/v1") is True
    assert endpoint_is_on_prem("http://localhost:11434/v1") is True
    assert endpoint_is_on_prem("http://box.local:1234/v1") is True
    assert endpoint_is_on_prem("http://10.0.0.7:1234/v1") is True
    assert endpoint_is_on_prem("https://api.openai.com/v1") is False
    assert endpoint_is_on_prem("http://8.8.8.8/v1") is False


# -- two backends in one process -------------------------------------------------

def test_two_backends_stay_independent_across_alternating_probes_and_an_invoke(server):
    """Today's module drifted [True, False] for the same caller inputs because
    invoke(model=) leaked into a global. Objects do not."""
    x = build(_spec(server.url, model="qwen/qwen3.8-35b"))
    y = build(_spec(server.url, model="some/other-model-on-disk"))     # listed, not loaded
    seq = [x.probe().ok, y.probe().ok, x.probe().ok, y.probe().ok]
    assert seq == [True, False, True, False]
    assert _ask(x).ok
    assert [x.probe().ok, y.probe().ok] == [True, False]


def test_capabilities_of_the_openai_compat_transport(server):
    caps = build(_spec(server.url, model="m")).capabilities
    assert {"schema", "model"} <= caps and "stream" not in caps
