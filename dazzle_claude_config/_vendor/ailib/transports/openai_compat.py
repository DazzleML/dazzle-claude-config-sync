"""The OpenAI-compatible HTTP transport: LM Studio, Ollama and llama.cpp on
this machine; OpenAI, OpenRouter, Groq, Together and the Llama endpoints
over the wire. One adapter. Local versus remote is the spec's endpoint and
whether it names a credential; nothing in the code knows the difference.

Stdlib only (`urllib`): no `requests`, no `openai` package.

**Everything unusual below is a measured fact, not a precaution**, taken
against LM Studio on real hardware while this transport's predecessor was
built (2026-09-04):

* ``response_format: {"type": "json_object"}`` is answered **HTTP 400** --
  unsupported -- while ``json_schema`` with ``strict`` works. So a strict
  schema is the only structured-output route here. The schema itself is the
  caller's: it arrives in the Request, and without one no shape is asked for.
* ``reasoning_effort: "none"`` is the only thinking-suppression that reaches
  the model through this API; it is a preset's business (`Spec.extra`), not
  the transport's, because a hosted provider may reject it.
* **HTTP 200 with empty content is possible** -- with reasoning on and a low
  token ceiling, every token went to reasoning and ``content`` came back
  ``''``. An empty body is a failure here, with a sentence.
* **Asking for a model that is not loaded makes a local server load it** --
  17.74 GB off disk in the measured case -- so the id is checked before
  anything is sent. ``/v1/models`` lists everything DOWNLOADED, not what is
  in memory (13 against 1, measured); load state comes from LM Studio's own
  ``/api/v0/models``, which hangs off the server ROOT, not off ``/v1``. A
  server without that endpoint (Ollama, llama.cpp, every hosted provider)
  answers "cannot say", a third value that must never be read as "nothing".
* **A client timeout does not cancel server-side work**, so there is no
  retry in here; the caller re-runs if it wants one. An HTTP error is
  reported with the server's own words and is not retried without the
  schema either -- a provider that rejects ``response_format`` for a routed
  model has said something the caller needs to hear.
* **Throughput is dominated by the configured context window, not by the
  model** (~385x between an oversized and a right-sized window on the same
  model). The probe reports the loaded window and warns above a threshold,
  so a caller can say so BEFORE a long job.
"""
from __future__ import annotations

import ipaddress
import json
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from ..types import MODEL, ON_PREM, SCHEMA, Readiness, Request, Response, Spec

#: How long to wait on a listing. If reachability takes longer than this the
#: server is not in a state to work with.
PROBE_TIMEOUT = 4

#: Above this many tokens the loaded window is far larger than a short
#: structured task needs, and on a machine whose VRAM the KV cache fills it
#: is the difference between seconds and minutes.
ROOMY_CONTEXT = 65536


def endpoint_is_on_prem(url: str) -> bool | None:
    """Whether a request to `url` stays on the user's own network, decided
    without a DNS lookup: an IP literal that is loopback, private or
    link-local; `localhost`; a `.local` name. A public host name is not.
    None when the URL has no host at all."""
    host = urlparse(url).hostname
    if not host:
        return None
    if host == "localhost" or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(ip.is_loopback or ip.is_private or ip.is_link_local)


class OpenAICompatible:
    """Stateless: every method takes the spec it is working for."""

    # -- plumbing ----------------------------------------------------------------

    def _headers(self, spec: Spec, *, post: bool = False) -> dict[str, str]:
        h = {"Accept": "application/json"}
        if post:
            h["Content-Type"] = "application/json"
        if spec.credential_env:
            h["Authorization"] = f"Bearer {os.environ.get(spec.credential_env, '')}"
        return h

    def _get(self, spec: Spec, url: str, timeout: int = PROBE_TIMEOUT):
        req = urllib.request.Request(url, headers=self._headers(spec))
        with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310
            return json.loads(r.read().decode("utf-8", "replace"))

    @staticmethod
    def _root(spec: Spec) -> str:
        ep = spec.endpoint.rstrip("/")
        return ep[:-3] if ep.endswith("/v1") else ep

    # -- the roster ----------------------------------------------------------------

    def models(self, spec: Spec) -> list[str] | None:
        """Model ids the server reports; None when it cannot be reached (or
        refuses the credential). Everything DOWNLOADED, not what is loaded."""
        try:
            body = self._get(spec, spec.endpoint.rstrip("/") + "/models")
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            return None
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            return None
        return [d["id"] for d in data if isinstance(d, dict) and isinstance(d.get("id"), str)]

    def _native_records(self, spec: Spec) -> list | None:
        try:
            body = self._get(spec, self._root(spec) + "/api/v0/models")
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            return None
        data = body.get("data") if isinstance(body, dict) else None
        return data if isinstance(data, list) else None

    def loaded_models(self, spec: Spec) -> list[str] | None:
        """Model ids actually in memory, or **None when the server cannot
        say**. Three-valued on purpose."""
        data = self._native_records(spec)
        if data is None:
            return None
        return [d["id"] for d in data if isinstance(d, dict) and isinstance(d.get("id"), str)
                and d.get("state") == "loaded"]

    def context_length(self, spec: Spec) -> int | None:
        data = self._native_records(spec)
        if data is None:
            return None
        for d in data:
            if isinstance(d, dict) and d.get("state") == "loaded":
                n = d.get("loaded_context_length") or d.get("max_context_length")
                return n if isinstance(n, int) else None
        return None

    def _target(self, spec: Spec) -> tuple[str, str]:
        """(model to ask for, why not) -- "" in the second slot means go.

        The order that avoids surprising a person: the spec's model if it is
        loaded; else the loaded one when the server can say; else the first
        listed, which is all a server without load state can offer."""
        ep = spec.endpoint.rstrip("/")
        if spec.credential_env and not os.environ.get(spec.credential_env):
            return "", (f"{spec.credential_env} is not set in the environment -- "
                        f"{spec.name or ep} needs a key there")
        listed = self.models(spec)
        if not listed:
            hint = f" ({spec.hint})" if spec.hint else ""
            return "", (f"no model server at {ep} -- start the local server{hint} "
                        f"or point at another endpoint")
        live = self.loaded_models(spec)          # None = the server cannot say
        if spec.model:
            if live is not None and spec.model not in live:
                where = ", ".join(live) if live else "none"
                return "", (f"model {spec.model!r} is not loaded on {ep} (loaded: {where}) -- "
                            f"asking for it would load it from disk; load it first or name one "
                            f"that is")
            if live is None and spec.model not in listed:
                return "", f"model {spec.model!r} is not on {ep} -- it has: {', '.join(listed)}"
            return spec.model, ""
        if live:
            return live[0], ""                   # the one in memory, not the first on disk
        if live is not None:                     # the server can say, and says: nothing
            return "", (f"{ep} has no model loaded -- load one (asking would load one "
                        f"from disk, which takes minutes)")
        return listed[0], ""

    # -- the protocol ---------------------------------------------------------------

    def capabilities(self, spec: Spec) -> frozenset[str]:
        caps = {SCHEMA, MODEL}
        on_prem = spec.on_prem if spec.on_prem is not None else endpoint_is_on_prem(spec.endpoint)
        if on_prem:
            caps.add(ON_PREM)
        return frozenset(caps)

    def probe(self, spec: Spec) -> Readiness:
        model, why = self._target(spec)
        if not model:
            return Readiness(False, why)
        ep = spec.endpoint.rstrip("/")
        n = self.context_length(spec)
        reason = f"{ep} -- reachable, model {model}" + (f", {n:,}-token context" if n else "")
        warning = ""
        if n and n > ROOMY_CONTEXT:
            warning = (f"loaded with a {n:,}-token context; a short structured task needs a "
                       f"couple of thousand, and an oversized window is the usual reason a local "
                       f"run takes minutes (reload it at 16k-32k)")
        return Readiness(True, reason, warning)

    def invoke(self, spec: Spec, req: Request) -> Response:
        model, why = self._target(spec)
        if not model:
            return Response("failed", error=why)
        ep = spec.endpoint.rstrip("/")
        body: dict = {"model": model,
                      "messages": [{"role": "user", "content": req.prompt}],
                      "stream": False}
        honoured = [MODEL]
        if req.temperature is not None:
            body["temperature"] = req.temperature
        if req.max_tokens is not None:
            body["max_tokens"] = req.max_tokens
            honoured.append("max_tokens")
        body.update(dict(spec.extra))
        if req.schema is not None:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "answer", "strict": True,
                                                       "schema": req.schema}}
            honoured.append(SCHEMA)
        http = urllib.request.Request(ep + "/chat/completions", data=json.dumps(body).encode("utf-8"),
                                      headers=self._headers(spec, post=True), method="POST")
        started = time.monotonic()
        try:
            with urllib.request.urlopen(http, timeout=req.timeout) as r:   # noqa: S310
                answer = json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:                                            # noqa: BLE001
                pass
            return Response("failed", error=f"{ep} answered HTTP {e.code}{': ' + detail if detail else ''}")
        except TimeoutError:
            return Response("failed", error=(f"no answer from {model} within {req.timeout}s -- if it is "
                                             f"generating slowly, the usual cause is a context window "
                                             f"far larger than the prompt, not the model itself"))
        except (urllib.error.URLError, OSError) as e:
            return Response("failed", error=f"cannot reach {ep}: {e}")
        except ValueError as e:
            return Response("failed", error=f"{ep} answered something that is not JSON: {e}")
        elapsed = time.monotonic() - started
        choices = answer.get("choices") if isinstance(answer, dict) else None
        if not choices:
            return Response("failed", error=f"{ep} answered with no choices", elapsed=elapsed)
        text = (choices[0].get("message") or {}).get("content") or ""
        if not text.strip():
            return Response("failed", model_used=model, elapsed=elapsed,
                            error=(f"{model} answered with empty content -- the reasoning budget may "
                                   f"have consumed the reply; raise max_tokens or turn reasoning off"))
        return Response("answered", text=text, model_used=str(answer.get("model") or model),
                        honoured=tuple(honoured), elapsed=elapsed)
