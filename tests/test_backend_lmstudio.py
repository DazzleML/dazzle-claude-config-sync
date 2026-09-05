"""The `lmstudio` backend: a model answering on your own machine.

It lives in the vendored library (`_vendor/ailib/backends/lmstudio.py`)
because an HTTP-server backend is something the shared library wants,
not a ccs peculiarity -- so this file imports it the way any consumer
would, through the package rather than through ccs.

Against a real socket, not a mock. The backend's whole job is to speak HTTP
to something that is not ccs, and a mocked `urlopen` would prove only that
we can call our own code -- it would not catch a malformed request body, a
wrong path, or a header the other end refuses. The fake server here is
stdlib `http.server` on an ephemeral port, and it records what it was
actually sent.

Every case below is a measured hazard from the evaluation this backend was
written against (notepad-cleanup's 2026-07-26 addendum), not an invented
edge: an unloaded model that would JIT-load gigabytes, an HTTP 200 whose
content is empty because reasoning ate the budget, and a server that is
simply not running because the local server was never started.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from dazzle_claude_config._vendor.ailib.backends import lmstudio as ailocal

ANSWER = {"hunks": [{"hunk": 1, "lines": ["T1"], "rules": [], "rationale": "upstream"}]}


class _Fake:
    """A stand-in LM Studio, shaped like the real one.

    The two model listings are DIFFERENT on purpose, because the real server
    is: ``/v1/models`` names everything downloaded, and only LM Studio's own
    ``/api/v0/models`` carries the ``state`` that says what is in memory --
    measured live as 13 listed against 1 loaded. `native` turns that second
    endpoint off, which is how an Ollama or llama.cpp endpoint behaves.
    """
    models = ["qwen/qwen3.8-35b", "some/other-model-on-disk"]
    loaded = ["qwen/qwen3.8-35b"]
    context = 16384
    max_context = 262144
    native = True
    content = json.dumps(ANSWER)
    status = 200
    sent: dict | None = None


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

    def do_GET(self):
        if self.path.startswith("/api/v0/models"):
            if not _Fake.native:
                self._json({"error": "not found"}, 404)
                return
            self._json({"data": [
                {"id": m, "state": "loaded" if m in _Fake.loaded else "not-loaded",
                 "loaded_context_length": _Fake.context if m in _Fake.loaded else None,
                 "max_context_length": _Fake.max_context}
                for m in _Fake.models]})
        elif self.path.endswith("/v1/models"):
            self._json({"data": [{"id": m} for m in _Fake.models]})
        else:
            self._json({"error": "no"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        _Fake.sent = json.loads(self.rfile.read(n).decode())
        if _Fake.status != 200:
            self._json({"error": {"message": "response_format not supported"}}, _Fake.status)
            return
        self._json({"choices": [{"message": {"content": _Fake.content}}]})


@pytest.fixture
def server():
    _Fake.models = ["qwen/qwen3.8-35b", "some/other-model-on-disk"]
    _Fake.loaded = ["qwen/qwen3.8-35b"]
    _Fake.context = 16384
    _Fake.max_context = 262144
    _Fake.native = True
    _Fake.content = json.dumps(ANSWER)
    _Fake.status = 200
    _Fake.sent = None
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{srv.server_port}/v1"
    ailocal.configure(endpoint=url, model="")
    from dazzle_claude_config.aiprompt import ANSWER_SCHEMA
    ailocal.set_schema(ANSWER_SCHEMA)
    yield srv
    srv.shutdown()
    srv.server_close()
    ailocal.configure(endpoint=ailocal.DEFAULT_ENDPOINT, model="")
    ailocal.set_schema(None)


def test_a_loaded_model_answers_and_the_answer_comes_back(server):
    assert ailocal.is_available() is True
    ok, text = ailocal.invoke("resolve this", timeout=10)
    assert ok is True
    assert json.loads(text) == ANSWER


def test_the_request_asks_for_a_strict_schema_not_a_json_object(server):
    """The measured fact this backend exists around: LM Studio answers
    `json_object` with HTTP 400, while `json_schema` + strict works -- so
    the schema is the only structured-output route, and sending the wrong
    one fails every merge on a real server."""
    ailocal.invoke("resolve this", timeout=10)
    fmt = _Fake.sent["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    schema = fmt["json_schema"]["schema"]
    item = schema["properties"]["hunks"]["items"]
    assert set(item["required"]) == {"hunk", "lines", "rules", "rationale"}
    assert item["additionalProperties"] is False       # no room for invented fields
    assert _Fake.sent["reasoning_effort"] == "none"    # the only toggle that reaches it
    assert _Fake.sent["stream"] is False
    assert _Fake.sent["temperature"] == 0


def test_a_downloaded_but_unloaded_model_is_refused_before_anything_is_sent(server):
    """The distinction a listing check cannot make. `some/other-model-on-disk`
    IS in /v1/models -- it is downloaded -- and naming it would make LM Studio
    load it from disk. Only the load state says so, and nothing is POSTed.

    Measured live before this test existed: 13 models listed, 1 loaded. A
    check against the listing would have waved twelve of them through."""
    ailocal.configure(model="some/other-model-on-disk")
    assert "some/other-model-on-disk" in ailocal.models()      # downloaded...
    assert "some/other-model-on-disk" not in (ailocal.loaded_models() or [])   # ...not loaded
    ok, msg = ailocal.invoke("resolve this", timeout=10)
    assert ok is False
    assert "is not loaded" in msg and "qwen/qwen3.8-35b" in msg
    assert "load it from disk" in msg
    assert _Fake.sent is None                          # never reached the completion


def test_with_no_model_pinned_the_LOADED_one_is_chosen_not_the_first_listed(server):
    """`/v1/models` order is what is on disk, not what is in memory. Picking
    its first entry would have asked for a model the server would then load."""
    _Fake.models = ["some/other-model-on-disk", "qwen/qwen3.8-35b"]   # loaded one second
    ailocal.configure(model="")
    ok, _ = ailocal.invoke("resolve this", timeout=10)
    assert ok is True
    assert _Fake.sent["model"] == "qwen/qwen3.8-35b"


def test_a_server_without_the_native_api_still_works(server):
    """Ollama and llama.cpp speak the OpenAI surface and have no load state.
    "Cannot say" is a third value: it must not be read as "nothing loaded",
    or every merge on such an endpoint is refused."""
    _Fake.native = False
    assert ailocal.loaded_models() is None             # cannot say, not "none"
    assert ailocal.context_length() is None
    assert ailocal.is_available() is True
    ok, _ = ailocal.invoke("resolve this", timeout=10)
    assert ok is True


def test_an_oversized_context_window_is_named_before_a_merge_is_run(server):
    """The condition that made the first real run fail: a 197,120-token
    window on a 32 GB card, KV cache filling VRAM, 18.6 s to answer "ready".
    Reachable, so not an error -- but a person deserves to know before they
    wait two minutes for a merge."""
    _Fake.context = 197120
    assert ailocal.context_is_roomy() is True
    d = ailocal.describe()
    assert "197,120-token context" in d and "16k-32k" in d
    _Fake.context = 16384
    assert ailocal.context_is_roomy() is False
    assert "16,384-token context" in ailocal.describe()


def test_empty_content_on_http_200_is_a_failure_not_an_empty_answer(server):
    """Measured: with reasoning on and a low ceiling, every token went to
    reasoning and `content` came back ''. Read as an answer, that silently
    drops the file it was supposed to resolve."""
    _Fake.content = "   "
    ok, msg = ailocal.invoke("resolve this", timeout=10)
    assert ok is False and "empty content" in msg


def test_an_http_error_carries_the_servers_own_words(server):
    _Fake.status = 400
    ok, msg = ailocal.invoke("resolve this", timeout=10)
    assert ok is False and "HTTP 400" in msg and "response_format" in msg


def test_a_server_that_is_not_running_says_so_and_says_what_to_start():
    """The most likely failure by far: LM Studio's app is open but its
    local server was never started. 'Its CLI was not found' would send a
    person looking for the wrong thing."""
    ailocal.configure(endpoint="http://127.0.0.1:1/v1", model="")
    assert ailocal.is_available() is False
    assert ailocal.models() == []
    ok, msg = ailocal.invoke("resolve this", timeout=2)
    assert ok is False
    # the message names the thing to start, and names LM Studio as the
    # example rather than the assumption -- the backend serves any
    # OpenAI-compatible server
    assert "no model server" in msg and "start the local server" in msg
    assert "Developer tab" in msg
    assert "not reachable" in ailocal.describe()
    ailocal.configure(endpoint=ailocal.DEFAULT_ENDPOINT)


def test_describe_names_the_endpoint_and_what_is_loaded(server):
    d = ailocal.describe()
    assert "reachable" in d and "qwen/qwen3.8-35b" in d and "/v1" in d
    ailocal.configure(model="not/loaded")
    assert "is not loaded" in ailocal.describe()


def test_the_default_endpoint_is_the_ipv4_literal():
    """LM Studio binds IPv4-only on Windows; `localhost` can resolve to ::1
    first and time out under stream pressure. The literal is the fix, and
    it is a default rather than advice in a doc nobody reads."""
    assert ailocal.DEFAULT_ENDPOINT.startswith("http://127.0.0.1:")
    assert "localhost" not in ailocal.DEFAULT_ENDPOINT


def test_the_backend_is_registered_and_reachable_through_the_facade(server):
    from dazzle_claude_config import ailib
    assert "lmstudio" in ailib.backend_names()
    assert ailib.get_backend("lmstudio") is ailocal
    ailib.set_endpoint(ailocal.endpoint())
    ok, text = ailib.invoke("lmstudio", "resolve this", timeout=10)
    assert ok is True and json.loads(text) == ANSWER


# -- survivors of the v0.5.21 sweep, turned into tests -----------------------

def test_a_pinned_model_is_refused_when_the_server_says_NOTHING_is_loaded(server):
    """Mutation survivor m2, and the most dangerous of the sweep. The guard
    reads `live is not None`, not `live` -- because an EMPTY loaded list is
    the server saying "I have nothing in memory", which is a definite answer
    and not the same as "I cannot tell you". Under the truthy form the guard
    is skipped entirely and the request goes out, which is precisely the
    gigabytes-off-disk load this whole path exists to prevent."""
    _Fake.loaded = []                       # server CAN say, and says: nothing
    ailocal.configure(model="qwen/qwen3.8-35b")
    assert ailocal.loaded_models() == []     # a definite answer, not None
    ok, msg = ailocal.invoke("resolve this", timeout=10)
    assert ok is False
    assert "is not loaded" in msg and "loaded: none" in msg, msg
    assert _Fake.sent is None                # nothing was asked of the server


def test_with_nothing_loaded_and_no_pin_it_refuses_rather_than_choosing_one(server):
    """Mutation survivor m5's case from the other side: no model pinned and
    an empty roster must refuse, not fall through to the first DOWNLOADED
    model -- which the server would then have to load."""
    _Fake.loaded = []
    ailocal.configure(model="")
    ok, msg = ailocal.invoke("resolve this", timeout=10)
    assert ok is False
    assert "no model loaded" in msg and "takes minutes" in msg, msg
    assert _Fake.sent is None


def test_the_window_warning_is_about_exceeding_the_threshold_not_meeting_it(server):
    """Mutation survivor m1: `>` not `>=`. A window exactly at the threshold
    is the largest one still considered fit for the job; warning about it
    would train a person to ignore the warning."""
    _Fake.context = ailocal.ROOMY_CONTEXT
    assert ailocal.context_is_roomy() is False
    _Fake.context = ailocal.ROOMY_CONTEXT + 1
    assert ailocal.context_is_roomy() is True


def test_the_first_loaded_model_is_chosen_deterministically(server):
    """Mutation survivor m4. Which of two loaded models is asked is not a
    don't-care: the report names it, and it is part of the cache key, so a
    run that silently picked the other one would answer from a different
    model AND miss the cache."""
    _Fake.models = ["a/first", "b/second"]
    _Fake.loaded = ["a/first", "b/second"]
    ailocal.configure(model="")
    ok, _ = ailocal.invoke("resolve this", timeout=10)
    assert ok is True and _Fake.sent["model"] == "a/first"


def test_the_window_reported_is_the_one_LOADED_not_the_models_maximum(server):
    """Mutation survivor m9. LM Studio reports both, and they differ: on the
    machine this was built against, 197,120 loaded against a 262,144
    maximum. The maximum is a property of the model file; only the loaded
    window explains why a request is slow, and warning on the maximum would
    fire for models that are configured perfectly well."""
    _Fake.context = 8192            # loaded: small and fine
    _Fake.max_context = 262144      # capable of far more
    assert ailocal.context_length() == 8192
    assert ailocal.context_is_roomy() is False
    assert "8,192-token context" in ailocal.describe()
