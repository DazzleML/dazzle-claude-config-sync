"""The library's value types: what a backend IS on paper, what a call SAYS,
and what comes BACK.

A `Spec` is everything needed to build a backend -- which transport, where,
which model, how to authenticate, how to invoke a CLI -- and nothing that
varies per call. It is immutable, so it can be shared, hashed and recorded.
It holds the NAME of the environment variable carrying a credential and
never the credential itself: a spec is exactly the object that ends up in a
cache key, a provenance record and a health-check line, and a secret in a
frozen dataclass ends up in all three. `identity()` is the part of a spec
those consumers may see.

A `Request` is what varies per call and is the same for every transport: the
prompt, the shape the answer must take, the limits. The model is NOT here --
it is a fact about which backend you built, so it lives in the spec.

A `Response` says what happened with a word (answered, deferred, failed),
never with a boolean that has to mean three things.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass
from typing import Any, TextIO

STATUSES = ("answered", "deferred", "failed")

#: Capability names a transport may advertise for a given spec.
SCHEMA = "schema"                 # the answer's shape is enforced, not just requested
MODEL = "model"                   # the backend can be told which model to use
STREAM = "stream"                 # output can be echoed as it arrives
ON_PREM = "data_stays_on_prem"    # the prompt does not leave the user's own network


@dataclass(frozen=True)
class Spec:
    """Everything needed to BUILD a backend. Immutable.

    transport      -- "cli", "openai", "prompt-file", ... (the registry's names)
    name           -- a human label for the preset; not part of the identity
    endpoint       -- HTTP transports: the base URL, ending in /v1 for the
                      OpenAI-compatible surface; the prompt-file transport: the
                      directory prompts are written to
    model          -- the model to ask for; "" means the backend's own choice
    credential_env -- the NAME of the environment variable holding a bearer
                      token, resolved at request time; never the value
    command        -- CLI transports: the argv template. Placeholders:
                      {model}, {schema} (the schema inline, one argv token),
                      {schema_file}, {prompt_file}, {output_file} (paths in the
                      child's scratch directory), {cwd}. An empty placeholder
                      removes itself and the flag before it.
    answer         -- CLI transports: where the answer is. "stdout" (default),
                      "stdout-json:<key>" (stdout is a JSON envelope; take one
                      key), or "file:{output_file}"
    env_unset      -- variables removed from the CHILD's environment
    candidates     -- extra executable paths tried after PATH
    on_prem        -- the preset's word on whether data stays on the user's
                      network; None lets the transport derive it from the
                      endpoint
    hint           -- appended to a not-reachable reason (e.g. where to start
                      a local server); never part of the identity
    extra          -- transport-specific request fields, as ordered pairs
    """
    transport: str
    name: str = ""
    endpoint: str = ""
    model: str = ""
    credential_env: str = ""
    command: tuple[str, ...] = ()
    answer: str = "stdout"
    env_unset: tuple[str, ...] = ()
    candidates: tuple[str, ...] = ()
    on_prem: bool | None = None
    hint: str = ""
    extra: tuple[tuple[str, Any], ...] = ()

    def with_(self, **changes: Any) -> "Spec":
        return dataclasses.replace(self, **changes)

    def identity(self) -> str:
        """What a cache key, a record or a report may hold: the things that
        decide WHICH model answers. Never the credential's value; not the
        executable's resolved path (a reinstall must not flush a cache); not
        the name, the hint, the timeout or the candidates."""
        parts = [self.transport, self.endpoint.rstrip("/"), self.model, " ".join(self.command)]
        if self.extra:
            parts.append(json.dumps(sorted(self.extra), sort_keys=True, default=str))
        if self.credential_env:
            parts.append(f"key:{self.credential_env}")
        return "|".join(parts)


@dataclass(frozen=True)
class Request:
    """What varies per call. Identical for every transport.

    max_tokens=None and temperature=None mean "not sent": a low ceiling is
    exactly how a reasoning model comes back with empty content. `stream_to`
    is a text sink a transport echoes output into as it arrives; it is not
    part of the fingerprint, and neither is the timeout.
    """
    prompt: str
    schema: dict | None = None
    max_tokens: int | None = None
    timeout: int = 120
    temperature: float | None = 0
    stream_to: TextIO | None = None

    def fingerprint(self) -> str:
        payload = json.dumps({"prompt": self.prompt, "schema": self.schema,
                              "max_tokens": self.max_tokens, "temperature": self.temperature},
                             sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Response:
    """What came back. `status` is one of `STATUSES`:

    answered -- `text` holds the answer, `model_used` says who gave it,
                `honoured` names the Request fields the transport enforced
    deferred -- nothing was asked; `artifact` is where the prompt was written
                for a person to carry
    failed   -- `error` is a sentence a person can act on
    """
    status: str
    text: str = ""
    error: str = ""
    model_used: str = ""
    honoured: tuple[str, ...] = ()
    artifact: str = ""
    cached: bool = False
    cached_at: float = 0.0
    key: str = ""
    elapsed: float = 0.0

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}, not {self.status!r}")

    @property
    def ok(self) -> bool:
        return self.status == "answered"

    def with_(self, **changes: Any) -> "Response":
        return dataclasses.replace(self, **changes)


@dataclass(frozen=True)
class Readiness:
    """A health check's answer: yes or no, a sentence either way, and an
    optional warning for "yes, but" (a window far larger than the job)."""
    ok: bool
    reason: str = ""
    warning: str = ""
