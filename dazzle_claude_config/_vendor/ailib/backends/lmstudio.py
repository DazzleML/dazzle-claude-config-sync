"""Local OpenAI-compatible server backend (LM Studio, and anything like it).

The other backends in this package are CLI-shaped: an executable on PATH,
run as a subprocess. This one talks HTTP to a server the person is running
themselves, and that difference goes all the way through -- availability is
a connection rather than a file, the endpoint and the model are
configuration rather than discovery, and a failure means *the server is not
running* rather than *the CLI is not installed*.

It is also the position between the other two: `prompt_only` sends nothing
but makes a person carry the answer back by hand, and the hosted CLIs send
their text to somebody else's model. A local endpoint answers without
either. The property that matters is whether the data leaves the user's
control, not whether the process is on this machine -- `127.0.0.1` and a
LAN address both keep it, which is why the endpoint is configurable rather
than fixed to loopback.

Stdlib only (`urllib`): no `requests`, no `openai` package, so a tool
vendoring this library adds no dependency for it.

**Everything unusual below is a measured fact, not a precaution**, taken
against LM Studio on real hardware:

* ``response_format: {"type": "json_object"}`` is answered **HTTP 400** --
  unsupported -- while ``json_schema`` with ``strict`` works. That is the
  opposite of the usual assumption, and it means a strict schema is the
  only structured-output route here rather than a nicety. The schema itself
  belongs to the caller: `set_schema` takes it, and without one this
  backend asks for no particular shape.
* ``reasoning_effort: "none"`` is the only thinking-suppression that
  reaches the model through this API. ``chat_template_kwargs`` with
  ``enable_thinking: false`` and a ``/no_think`` prompt directive are both
  accepted and silently ignored. Measured cost of getting it wrong: a
  five-token reply took over 60 s with reasoning on and 22 s without.
* **HTTP 200 with empty content is possible** -- with reasoning on and a
  low token ceiling, every token went to reasoning and ``content`` came
  back ``''``. A caller that reads that as "no result" silently drops the
  work it asked about, so an empty body is a failure here, with a sentence.
* **Asking for a model that is not loaded makes the server load it** --
  17.74 GB off disk in the measured case -- so the id is checked before
  anything is sent. Note what ``/v1/models`` is: everything DOWNLOADED, not
  what is in memory. Measured live as 13 listed against 1 loaded, so a
  listing check alone would wave twelve gigabyte loads through. Load state
  comes from LM Studio's own ``/api/v0/models``; a server without that
  endpoint (Ollama, llama.cpp) answers "cannot say", which is a third value
  and must never be read as "nothing is loaded".
* That native API hangs off the server ROOT, beside the OpenAI-compatible
  surface rather than inside it. Appending it to a ``.../v1`` endpoint asks
  for ``/v1/api/v0/models`` and gets a 404 -- which presents as a working
  feature, because "cannot say" is legal.
* **A client timeout does not cancel server-side work**, so a blind retry
  queues behind the request it abandoned and makes throughput worse. There
  is no retry in here at all; the caller re-runs if it wants one.
* **Throughput is dominated by the configured context window, not by the
  model.** The same model on the same prompts went from 2386 s to 6.2 s
  (~385x) when an oversized window was reduced. Reproduced at 197,120
  tokens loaded on a 32 GB card: the KV cache had taken the whole card, the
  GPU sat at 5%, and "reply with the single word: ready" took 18.6 s warm.
  `context_length` exposes the number so a caller can say so BEFORE running
  a long job, and the timeout message names the same knob for anyone who
  gets there anyway.

The default endpoint is the IPv4 literal on purpose: LM Studio binds
IPv4-only on Windows, and ``localhost`` can resolve to ``::1`` first and
time out under stream pressure.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

#: The default endpoint. The IPv4 literal, never ``localhost`` -- see above.
DEFAULT_ENDPOINT = "http://127.0.0.1:1234/v1"

#: How long to wait on a listing. Reachability is a local question; if the
#: answer takes longer than this the server is not in a state to work with.
PROBE_TIMEOUT = 4

#: Above this many tokens the loaded window is far larger than a short
#: structured task needs, and on a machine whose VRAM the KV cache fills it
#: is the difference between seconds and minutes.
ROOMY_CONTEXT = 65536

_endpoint = DEFAULT_ENDPOINT
_model = ""          # "" means: whatever the server has loaded
_schema = None       # the caller's strict JSON schema, or None for no shape


def configure(endpoint=None, model=None, schema=None):
    """Point the backend at a server, optionally pin a model, optionally set
    the answer schema.

    The mirror of `prompt_only.set_output_dir`: a backend that needs a
    per-installation fact is told it, rather than reading any particular
    tool's configuration itself.
    """
    global _endpoint, _model, _schema
    if endpoint:
        _endpoint = str(endpoint).rstrip("/")
    if model is not None:
        _model = str(model)
    if schema is not None:
        _schema = schema


def set_schema(schema):
    """The JSON schema the answer must satisfy, or None for no constraint.

    The mechanism is this library's; the shape is the caller's. Passing one
    is what makes a small local model structurally unable to reply with
    prose instead of an answer.
    """
    global _schema
    _schema = schema


def endpoint():
    """The endpoint in force, for a caller's report or health check."""
    return _endpoint


def _get(path, timeout=PROBE_TIMEOUT):
    req = urllib.request.Request(_endpoint + path, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310 (local http)
        return json.loads(r.read().decode("utf-8", "replace"))


def _get_native(path, timeout=PROBE_TIMEOUT):
    """GET off the server ROOT rather than off ``/v1``.

    LM Studio's own API sits beside the OpenAI-compatible surface, not
    inside it; appending it to the configured endpoint silently 404s.
    """
    root = _endpoint[:-3] if _endpoint.endswith("/v1") else _endpoint
    req = urllib.request.Request(root.rstrip("/") + path,
                                 headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310 (local http)
        return json.loads(r.read().decode("utf-8", "replace"))


def models():
    """Model ids the server reports, or [] when it cannot be reached.

    Everything DOWNLOADED, not what is in memory -- see `loaded_models`.
    """
    try:
        body = _get("/models")
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return []
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        return []
    return [d["id"] for d in data if isinstance(d, dict) and isinstance(d.get("id"), str)]


def _native_records():
    try:
        body = _get_native("/api/v0/models")
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None
    data = body.get("data") if isinstance(body, dict) else None
    return data if isinstance(data, list) else None


def loaded_models():
    """Model ids actually in memory, or **None when the server cannot say**.

    Three-valued on purpose: a list, or None for an endpoint with no load
    state (Ollama, llama.cpp). Reading None as an empty list would refuse
    every request against those servers.
    """
    data = _native_records()
    if data is None:
        return None
    return [d["id"] for d in data if isinstance(d, dict) and isinstance(d.get("id"), str)
            and d.get("state") == "loaded"]


def context_length():
    """Tokens the loaded model was given, or None when the server cannot say.

    Worth asking because an oversized window is the single most likely
    reason a local request takes minutes, and it presents as a slow model
    rather than as a setting.
    """
    data = _native_records()
    if data is None:
        return None
    for d in data:
        if isinstance(d, dict) and d.get("state") == "loaded":
            n = d.get("loaded_context_length") or d.get("max_context_length")
            return n if isinstance(n, int) else None
    return None


def context_is_roomy():
    """True when the loaded window is far larger than a short task needs."""
    n = context_length()
    return bool(n and n > ROOMY_CONTEXT)


def _target():
    """(model to ask for, why not) -- "" in the second slot means go ahead.

    The order that avoids surprising a person: the pinned model if it is
    loaded; else the loaded one when the server can say which; else the
    first listed, which is all a server without load state can offer.
    """
    listed = models()
    if not listed:
        return "", (f"no model server at {_endpoint} -- start the local server "
                    f"(in LM Studio: the Developer tab) or point at another endpoint")
    live = loaded_models()          # None = the server cannot say
    if _model:
        if live is not None and _model not in live:
            where = ", ".join(live) if live else "none"
            return "", (f"model {_model!r} is not loaded on {_endpoint} (loaded: {where}) -- "
                        f"asking for it would load it from disk; load it first or name one "
                        f"that is")
        if live is None and _model not in listed:
            return "", (f"model {_model!r} is not on {_endpoint} -- it has: "
                        f"{', '.join(listed)}")
        return _model, ""
    if live:
        return live[0], ""          # the one in memory, not the first of everything on disk
    if live is not None:            # the server can say, and says nothing is loaded
        return "", (f"{_endpoint} has no model loaded -- load one (asking would load one "
                    f"from disk, which takes minutes)")
    return listed[0], ""


def is_available():
    """True when the server answers AND has a model ready to answer with.

    Deliberately not a bare TCP check, and deliberately not "a model is
    listed" either: a listing proves only that the disk has one.
    """
    return bool(_target()[0])


def describe():
    """One line for a caller's health check: where it looked, what it found."""
    model, why = _target()
    if not model:
        if not models():
            return f"{_endpoint} -- not reachable (is the local server started?)"
        return f"{_endpoint} -- {why}"
    n = context_length()
    if n and n > ROOMY_CONTEXT:
        return (f"{_endpoint} -- reachable, model {model}, but loaded with a "
                f"{n:,}-token context; a short structured task needs a couple of thousand, "
                f"and an oversized window is the usual reason a local run takes minutes "
                f"(reload it at 16k-32k)")
    return f"{_endpoint} -- reachable, model {model}" + (f", {n:,}-token context" if n else "")


def invoke(prompt, verbose=False, timeout=120):
    """Ask the local model; ``(success, text)`` as this package's contract has it.

    `verbose` is accepted for contract compatibility and unused: there is no
    subprocess whose chatter could be streamed, and this is one call.
    """
    model, why = _target()
    if not model:
        return False, why
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "stream": False,
        "reasoning_effort": "none",
    }
    if _schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "answer", "strict": True, "schema": _schema},
        }
    req = urllib.request.Request(
        _endpoint + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (local http)
            answer = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:                                        # noqa: BLE001
            pass
        return False, f"{_endpoint} answered HTTP {e.code}{': ' + detail if detail else ''}"
    except TimeoutError:
        return False, (f"no answer from {model} within {timeout}s -- if it is generating "
                       f"slowly, the usual cause is a context window far larger than the "
                       f"prompt, not the model itself")
    except (urllib.error.URLError, OSError) as e:
        return False, f"cannot reach {_endpoint}: {e}"
    except ValueError as e:
        return False, f"{_endpoint} answered something that is not JSON: {e}"
    choices = answer.get("choices") if isinstance(answer, dict) else None
    if not choices:
        return False, f"{_endpoint} answered with no choices"
    text = (choices[0].get("message") or {}).get("content") or ""
    if not text.strip():
        # Measured: reasoning can consume the whole budget and leave content
        # empty. Reading that as "nothing to do" would drop the work.
        return False, (f"{model} answered with empty content -- the reasoning budget may "
                       f"have consumed the reply; try a larger max token limit")
    return True, text
