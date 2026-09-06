"""The AI object: a `Spec` bound to a `Transport`.

A backend holds its spec and delegates to a transport. It keeps no module
state, so two backends built from two specs can live in one process -- for
a caller that asks several models in one run, or one that lives longer than
a single call -- and neither can leak into the other.

Transports are registered by name. The three shipped here are lazily
imported the first time a backend is built; a consumer (or a test) may
register its own with `register_transport`.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import Readiness, Request, Response, Spec


@runtime_checkable
class Transport(Protocol):
    """One per WAY OF REACHING a model. Stateless: everything comes from the
    spec it is handed, so the same transport object serves every backend
    built over it."""

    def probe(self, spec: Spec) -> Readiness: ...
    def invoke(self, spec: Spec, req: Request) -> Response: ...
    def capabilities(self, spec: Spec) -> frozenset[str]: ...


_TRANSPORTS: dict[str, Transport] = {}
_BUILTIN = ("cli", "openai", "prompt-file")


def register_transport(name: str, transport: Transport | None) -> None:
    """Add a transport under `name`, or remove it with None."""
    if transport is None:
        _TRANSPORTS.pop(name, None)
    else:
        _TRANSPORTS[name] = transport


def _ensure_builtins() -> None:
    if all(n in _TRANSPORTS for n in _BUILTIN):
        return
    from .transports import cli, openai, prompt_file
    _TRANSPORTS.setdefault("cli", cli.SubprocessCli())
    _TRANSPORTS.setdefault("openai", openai.OpenAICompatible())
    _TRANSPORTS.setdefault("prompt-file", prompt_file.PromptFile())


def transport_names() -> list[str]:
    _ensure_builtins()
    return sorted(_TRANSPORTS)


def transport_for(name: str) -> Transport:
    _ensure_builtins()
    try:
        return _TRANSPORTS[name]
    except KeyError:
        raise ValueError(f"unknown transport {name!r} -- one of: {', '.join(sorted(_TRANSPORTS))}") from None


class Backend:
    """The object a caller talks to. Build one with `build(spec)`."""

    def __init__(self, spec: Spec):
        self.spec = spec
        self._transport = transport_for(spec.transport)

    @property
    def identity(self) -> str:
        return self.spec.identity()

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(self._transport.capabilities(self.spec))

    def probe(self) -> Readiness:
        return self._transport.probe(self.spec)

    def invoke(self, req: Request) -> Response:
        return self._transport.invoke(self.spec, req)

    def __repr__(self) -> str:
        return f"Backend({self.spec.name or self.spec.transport}: {self.identity})"


def build(spec: Spec) -> Backend:
    return Backend(spec)
