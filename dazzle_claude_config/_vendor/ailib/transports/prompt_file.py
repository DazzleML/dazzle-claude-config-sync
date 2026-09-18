"""The prompt-file transport: not a model. It writes the request where a
person can carry it to any model by hand, and answers "deferred" -- which
is a status, not a failure and not a success. A caller that wants a
"write the prompt and stop" mode without routing through the library is
free to do that itself; this exists so the library's own story is complete
and so a consumer that DOES want it has it.

The spec's `endpoint` is the directory prompts are written to.
"""
from __future__ import annotations

import time
from pathlib import Path

from ..types import ON_PREM, Readiness, Request, Response, Spec


class PromptFile:
    def capabilities(self, spec: Spec) -> frozenset[str]:
        return frozenset({ON_PREM})                    # nothing leaves at all

    def probe(self, spec: Spec) -> Readiness:
        if not spec.endpoint:
            return Readiness(False, "no directory configured for prompts (the spec's endpoint)")
        return Readiness(True, f"prompts are written to {spec.endpoint}; nothing is sent")

    def invoke(self, spec: Spec, req: Request) -> Response:
        if not spec.endpoint:
            return Response("failed", error="no directory configured for prompts (the spec's endpoint)")
        d = Path(spec.endpoint).expanduser()
        try:
            d.mkdir(parents=True, exist_ok=True)
            path = d / f"prompt_{time.strftime('%Y-%m-%d_%H-%M-%S')}.md"
            n = 1
            while path.exists():                       # two in one second
                n += 1
                path = d / f"prompt_{time.strftime('%Y-%m-%d_%H-%M-%S')}_{n}.md"
            path.write_text(req.prompt, encoding="utf-8")
        except OSError as e:
            return Response("failed", error=f"cannot write the prompt under {d}: {e}")
        return Response("deferred", artifact=str(path))
