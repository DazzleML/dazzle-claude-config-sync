"""POC -- the AI object model: construct with configuration, invoke with a request.

Settles whether the shape proposed on 2026-09-05 (rethink verdict NARROWED:
construction versus invocation is the perpendicular; refactor-advisor rows
4-7, 9-11, 13) actually holds, before a design document commits to it.

THE PROPOSAL. A backend is a VALUE (Spec: transport, endpoint, model, a
credential *reference*, an argv template) plus a BEHAVIOUR (Transport). The
caller says `build(spec)` once, then `backend.probe()` and
`backend.invoke(Request)` -- and the Request (prompt, required answer shape,
limits) is identical for every transport. Local versus remote is a URL and
whether a credential is named. prompt-only is not a backend; it is a Response
whose status is "deferred".

PREDICTIONS, written before running (each arm's pass criterion is exact):

  A. one caller function, containing no transport or vendor branch, drives four
     backends (subprocess CLI, OpenAI-compatible local, OpenAI-compatible remote
     with a bearer token, prompt-file) -> statuses answered, answered, answered,
     deferred, and the three answers parse to the same line ids.
  B. the wtf-locked consumer (a prose answer split into sections) goes through
     the SAME backend.invoke as the ccs consumer -> 4 sections parsed. One door.
  C. two backends built from two specs against one server that has loaded only
     model-A, probed alternately four times -> [True, False, True, False].
     CONTROL (today's lmstudio module, same scenario) -> the second probe of the
     SAME configuration answers differently from the first, because invoke()
     leaked the model into a module global. Predicted [True, False].
  D. the credential's VALUE appears in none of identity(), repr(spec), or the
     record-shaped serialisation, and the remote request carried
     `Authorization: Bearer`. CONTROL (today's lmstudio.py against the
     token-requiring server) -> cannot list models (401), so is_available is
     False: no auth header exists in the library today.
  E. os.getcwd() and os.environ are byte-identical before and after every
     invoke in arms A-D: the transport hands cwd and env to the subprocess
     rather than mutating the process. (No control: today's facade restores
     both in `finally`, so the mutation is invisible from outside a call.)

FALLBACKS. A fails -> the Request type lacks something a transport needs;
name it. C's control PASSES -> the method is broken, report nothing. D's
control PASSES -> today's code has an auth path I missed; re-check row 7.

Fake servers only (stdlib http.server on ephemeral ports); a fake CLI written
to a temp dir; no hosted CLI, no real model, no network beyond loopback.
Production source is untouched -- prove it with `git status` afterwards.

Run from the worktree root:  python -B tests/one-offs/thinking/ai-object-model/poc_ai_object_model.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

# =============================================================================
# The proposed library shape. Would live in _vendor/ailib; knows nothing of ccs.
# =============================================================================

@dataclass(frozen=True)
class Spec:
    """Everything needed to BUILD a backend. Immutable; safe to hash, log, record.

    `credential_env` is the NAME of an environment variable, never the secret:
    a spec is exactly the object that ends up in a cache key and a provenance
    record, and a secret in a frozen dataclass ends up in both.
    """
    transport: str                        # "cli" | "openai" | "prompt-file"
    name: str = ""                        # the preset's human name
    endpoint: str = ""                    # openai: base URL ending in /v1
    model: str = ""                       # default model; "" = the server's choice
    credential_env: str = ""              # openai: env var holding the bearer token
    command: tuple[str, ...] = ()         # cli: argv template, "{model}" substituted
    output_dir: str = ""                  # prompt-file: where prompts are written
    extra: tuple[tuple[str, Any], ...] = ()  # transport-specific request extras

    def identity(self) -> str:
        """What a cache key or record may hold. Never the credential's value."""
        return "|".join((self.transport, self.endpoint, self.model, " ".join(self.command),
                         self.credential_env and f"key:{self.credential_env}"))


@dataclass(frozen=True)
class Request:
    prompt: str
    schema: dict | None = None            # the shape the answer must take, if any
    max_tokens: int = 4096
    timeout: int = 60


@dataclass(frozen=True)
class Response:
    status: str                           # "answered" | "deferred" | "failed"
    text: str = ""
    error: str = ""
    model_used: str = ""
    honoured: tuple[str, ...] = ()        # which Request fields the transport enforced
    artifact: str = ""                    # deferred: where the prompt was written

    @property
    def ok(self) -> bool:
        return self.status == "answered"


@dataclass(frozen=True)
class Readiness:
    ok: bool
    reason: str = ""


class Transport:
    """One per WAY OF REACHING a model. Stateless: everything comes from the spec."""
    def probe(self, spec: Spec) -> Readiness: raise NotImplementedError
    def invoke(self, spec: Spec, req: Request) -> Response: raise NotImplementedError


class OpenAICompatible(Transport):
    """LM Studio, Ollama, OpenAI, OpenRouter, Groq... one adapter. Local or
    remote is the endpoint and whether a credential is named."""
    def _headers(self, spec: Spec) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if spec.credential_env:
            h["Authorization"] = f"Bearer {os.environ.get(spec.credential_env, '')}"
        return h

    def _get(self, spec: Spec, path: str) -> Any:
        r = urllib.request.Request(spec.endpoint.rstrip("/") + path, headers=self._headers(spec))
        with urllib.request.urlopen(r, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def models(self, spec: Spec) -> list[str] | None:
        try:
            return [m["id"] for m in self._get(spec, "/models").get("data", [])]
        except (urllib.error.URLError, OSError, ValueError):
            return None

    def loaded(self, spec: Spec) -> list[str] | None:
        """Three-valued on purpose (lmstudio.py's hook): None = cannot say."""
        try:
            root = spec.endpoint.rstrip("/")
            root = root[:-3] if root.endswith("/v1") else root
            r = urllib.request.Request(root + "/api/v0/models", headers=self._headers(spec))
            with urllib.request.urlopen(r, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8")).get("data", [])
            return [m["id"] for m in data if m.get("state") == "loaded"]
        except (urllib.error.URLError, OSError, ValueError):
            return None

    def probe(self, spec: Spec) -> Readiness:
        listed = self.models(spec)
        if listed is None:
            return Readiness(False, f"no model server at {spec.endpoint}")
        if spec.model:
            live = self.loaded(spec)
            if live is not None and spec.model not in live:
                return Readiness(False, f"model {spec.model!r} is not loaded (loaded: {', '.join(live) or 'none'})")
            if live is None and spec.model not in listed:
                return Readiness(False, f"model {spec.model!r} is not on {spec.endpoint}")
        return Readiness(True)

    def invoke(self, spec: Spec, req: Request) -> Response:
        body: dict[str, Any] = {"model": spec.model or (self.models(spec) or [""])[0],
                                "messages": [{"role": "user", "content": req.prompt}],
                                "max_tokens": req.max_tokens, **dict(spec.extra)}
        honoured = ["model", "max_tokens"]
        if req.schema is not None:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "answer", "strict": True, "schema": req.schema}}
            honoured.append("schema")
        data = json.dumps(body).encode("utf-8")
        r = urllib.request.Request(spec.endpoint.rstrip("/") + "/chat/completions",
                                   data=data, headers=self._headers(spec), method="POST")
        try:
            with urllib.request.urlopen(r, timeout=req.timeout) as resp:
                out = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return Response("failed", error=f"HTTP {e.code} from {spec.endpoint}")
        except (urllib.error.URLError, OSError) as e:
            return Response("failed", error=str(e))
        content = (out.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        if not content:
            return Response("failed", error="HTTP 200 with empty content", model_used=out.get("model", ""))
        return Response("answered", text=content, model_used=out.get("model", body["model"]),
                        honoured=tuple(honoured))


class SubprocessCli(Transport):
    """claude, codex, pi, gemini-cli: an executable, argv from a template, the
    prompt on stdin. cwd and env are PASSED to the child, never set on this
    process -- the property a long-lived caller (a GUI) cannot do without."""
    def probe(self, spec: Spec) -> Readiness:
        exe = spec.command[0] if spec.command else ""
        if exe and (Path(exe).is_file() or shutil.which(exe)):
            return Readiness(True)
        return Readiness(False, f"{exe or '(no command)'} is not on PATH")

    def invoke(self, spec: Spec, req: Request) -> Response:
        argv = [a.replace("{model}", spec.model) for a in spec.command]
        honoured = ("model",) if any("{model}" in a for a in spec.command) and spec.model else ()
        scratch = tempfile.mkdtemp(prefix="poc-cli-")
        try:
            child_env = dict(os.environ)          # a COPY, handed to the child
            child_env["AI_TIMEOUT"] = str(req.timeout)
            p = subprocess.run(argv, input=req.prompt, capture_output=True, text=True,
                               timeout=req.timeout, cwd=scratch, env=child_env)
        except (OSError, subprocess.TimeoutExpired) as e:
            return Response("failed", error=str(e))
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        if p.returncode != 0:
            return Response("failed", error=(p.stderr or p.stdout).strip()[:200])
        return Response("answered", text=p.stdout, model_used=spec.model, honoured=honoured)


class PromptFile(Transport):
    """Not a model: writes the request where a person can carry it. The answer
    is DEFERRED, which is a status, not a failure and not a success."""
    def probe(self, spec: Spec) -> Readiness:
        return Readiness(bool(spec.output_dir), "no output directory configured")

    def invoke(self, spec: Spec, req: Request) -> Response:
        d = Path(spec.output_dir); d.mkdir(parents=True, exist_ok=True)
        path = d / "prompt.md"
        path.write_text(req.prompt, encoding="utf-8")
        return Response("deferred", artifact=str(path))


_TRANSPORTS: dict[str, Transport] = {"openai": OpenAICompatible(), "cli": SubprocessCli(),
                                     "prompt-file": PromptFile()}


class Backend:
    """The AI object. Holds its spec; delegates to its transport. No globals."""
    def __init__(self, spec: Spec):
        self.spec = spec
        self._t = _TRANSPORTS[spec.transport]

    @property
    def identity(self) -> str:
        return self.spec.identity()

    def probe(self) -> Readiness:
        return self._t.probe(self.spec)

    def invoke(self, req: Request) -> Response:
        return self._t.invoke(self.spec, req)


def build(spec: Spec) -> Backend:
    return Backend(spec)


# =============================================================================
# Two consumers. Neither names a transport or a vendor. That is the claim.
# =============================================================================

ANSWER_SCHEMA = {"type": "object", "properties": {"hunks": {"type": "array"}}, "required": ["hunks"]}


def ccs_merge_step(backend: Backend, prompt: str) -> tuple[str, Any]:
    """ccs: structured answer, line ids, parsed by the caller."""
    ready = backend.probe()
    if not ready.ok:
        return "backend-failed", ready.reason
    resp = backend.invoke(Request(prompt=prompt, schema=ANSWER_SCHEMA))
    if resp.status == "deferred":
        return "prompt-written", resp.artifact
    if not resp.ok:
        return "backend-failed", resp.error
    return "answered", json.loads(resp.text)["hunks"]


def locked_step(backend: Backend, prompt: str) -> tuple[str, Any]:
    """wtf locked: prose answer, four labelled sections, parsed by the caller."""
    resp = backend.invoke(Request(prompt=prompt))
    if not resp.ok:
        return resp.status, resp.error
    sections = {}
    for chunk in resp.text.split("## ")[1:]:
        head, _, body = chunk.partition("\n")
        sections[head.strip()] = body.strip()
    return "answered", sections


# =============================================================================
# Fakes
# =============================================================================

class FakeOpenAI:
    """An OpenAI-compatible server. Optionally requires a bearer token. Answers
    JSON when a response_format is requested, prose otherwise. Records requests."""
    def __init__(self, require_token: str | None = None, loaded: tuple[str, ...] = ("model-A",)):
        self.require_token, self.loaded = require_token, loaded
        self.requests: list[dict] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def _auth_ok(self):
                if outer.require_token is None:
                    return True
                return self.headers.get("Authorization") == f"Bearer {outer.require_token}"
            def _send(self, code, obj):
                b = json.dumps(obj).encode(); self.send_response(code)
                self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
                self.end_headers(); self.wfile.write(b)
            def do_GET(self):
                if not self._auth_ok():
                    return self._send(401, {"error": "unauthorized"})
                if self.path == "/v1/models":
                    return self._send(200, {"data": [{"id": "model-A"}, {"id": "model-B"}]})
                if self.path == "/api/v0/models":
                    return self._send(200, {"data": [{"id": m, "state": "loaded" if m in outer.loaded else "not-loaded"}
                                                     for m in ("model-A", "model-B")]})
                self._send(404, {})
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0)); body = json.loads(self.rfile.read(n) or b"{}")
                outer.requests.append({"model": body.get("model"), "auth": self.headers.get("Authorization"),
                                       "structured": "response_format" in body})
                if not self._auth_ok():
                    return self._send(401, {"error": "unauthorized"})
                if "response_format" in body:
                    content = json.dumps({"hunks": [{"n": 1, "choice": ["O1"]}]})
                else:
                    content = "## What Happened\nlock\n## Why\nidle\n## What To Do\nnothing\n## Confidence\nhigh"
                self._send(200, {"model": body.get("model"), "choices": [{"message": {"content": content}}]})
        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown(); self.server.server_close()


FAKE_CLI = '''import sys, json, os
args = sys.argv[1:]
model = args[args.index("--model") + 1] if "--model" in args else ""
prompt = sys.stdin.read()
print(json.dumps({"hunks": [{"n": 1, "choice": ["O1"]}], "model_seen": model, "cwd": os.getcwd()}))
'''


# =============================================================================
# Arms
# =============================================================================

rows: list[tuple[str, str, str]] = []


def verdict(arm: str, passed: bool, observed: str) -> None:
    rows.append((arm, "PASS" if passed else "FAIL", observed))


def main() -> int:
    cwd0, env0 = os.getcwd(), dict(os.environ)
    os.environ["POC_REMOTE_KEY"] = "s3cr3t-token-value"
    env0 = dict(os.environ)                          # the baseline includes the key we just set

    local = FakeOpenAI(require_token=None)
    remote = FakeOpenAI(require_token="s3cr3t-token-value")
    tmp = Path(tempfile.mkdtemp(prefix="poc-aiobj-"))
    cli_script = tmp / "fake_cli.py"; cli_script.write_text(FAKE_CLI, encoding="utf-8")

    specs = {
        "claude-ish (cli)":      Spec("cli", name="claude", model="opus", command=(sys.executable, str(cli_script), "--model", "{model}")),
        "lmstudio (openai, local)": Spec("openai", name="lmstudio", endpoint=local.url, model="model-A"),
        "openrouter (openai, remote)": Spec("openai", name="openrouter", endpoint=remote.url, model="model-A", credential_env="POC_REMOTE_KEY"),
        "prompt-only (file)":    Spec("prompt-file", name="prompt-only", output_dir=str(tmp / "prompts")),
    }
    try:
        # ---- A: one caller, four backends --------------------------------------
        outcomes = {name: ccs_merge_step(build(s), "merge this") for name, s in specs.items()}
        statuses = [o[0] for o in outcomes.values()]
        answers = {o[1][0]["choice"][0] for o in outcomes.values() if o[0] == "answered"}
        verdict("A one caller, four transports", statuses == ["answered"] * 3 + ["prompt-written"] and answers == {"O1"},
                f"statuses={statuses}, ids={sorted(answers)}")
        src = Path(__file__).read_text(encoding="utf-8")
        caller = src[src.index("def ccs_merge_step"):src.index("def locked_step")]
        verdict("A' the caller names no transport/vendor",
                not any(w in caller for w in ("cli", "openai", "lmstudio", "claude", "codex", "transport")),
                f"{caller.count(chr(10))} lines, no transport or vendor token")

        # ---- B: the other consumer, the same door ------------------------------
        st, sections = locked_step(build(specs["lmstudio (openai, local)"]), "why did it lock")
        verdict("B locked's prose consumer through backend.invoke", st == "answered" and len(sections) == 4,
                f"{st}, sections={sorted(sections) if isinstance(sections, dict) else sections}")

        # ---- C: two backends, position independence ----------------------------
        x = build(Spec("openai", endpoint=local.url, model="model-A"))
        y = build(Spec("openai", endpoint=local.url, model="model-B"))     # B is listed, not loaded
        seq = [x.probe().ok, y.probe().ok, x.probe().ok, y.probe().ok]
        # and an invoke in between must not change the answer
        x.invoke(Request("q", schema=ANSWER_SCHEMA)); seq2 = [x.probe().ok, y.probe().ok]
        verdict("C two backends, alternating probes", seq == [True, False, True, False] and seq2 == [True, False],
                f"{seq} then after an invoke {seq2}")

        # CONTROL for C: today's module, same scenario, predicted to drift
        from dazzle_claude_config._vendor.ailib.backends import lmstudio as lm
        saved = (lm._endpoint, lm._model, lm._schema)
        try:
            lm.configure(endpoint=local.url, model=None, schema=None)
            first = lm.is_available()                        # caller: "is the server up?"
            lm.configure(model="model-B")                    # what ailib.invoke(model=) does today
            second = lm.is_available()                       # same caller question, next file
            verdict("C-control today's module drifts by position (must FAIL the property)",
                    first is True and second is False, f"[{first}, {second}] for the same caller inputs")
        finally:
            lm._endpoint, lm._model, lm._schema = saved

        # ---- D: credential hygiene, and remote reached with a bearer -----------
        rs = specs["openrouter (openai, remote)"]
        leaks = [w for w in ("identity", "repr", "record") if "s3cr3t" in
                 {"identity": rs.identity(), "repr": repr(rs), "record": json.dumps(asdict(rs))}[w]]
        remote_req = remote.requests[-1] if remote.requests else {}
        verdict("D secret absent from identity/repr/record; bearer sent",
                not leaks and remote_req.get("auth") == "Bearer s3cr3t-token-value" and remote_req.get("structured"),
                f"leaks={leaks}, remote saw auth={'yes' if remote_req.get('auth') else 'no'}, structured={remote_req.get('structured')}")

        # CONTROL for D: today's lmstudio.py against the keyed server
        saved = (lm._endpoint, lm._model, lm._schema)
        try:
            lm.configure(endpoint=remote.url, model="model-A", schema=ANSWER_SCHEMA)
            avail = lm.is_available()
            verdict("D-control today's lmstudio.py cannot reach a keyed server (must FAIL)",
                    avail is False, f"is_available={avail} -- no Authorization header exists today")
        finally:
            lm._endpoint, lm._model, lm._schema = saved

        # ---- E: no process-global side effects across everything above --------
        verdict("E cwd and environ unchanged by every invoke", os.getcwd() == cwd0 and dict(os.environ) == env0,
                f"cwd same={os.getcwd() == cwd0}, environ same={dict(os.environ) == env0}")
    finally:
        local.stop(); remote.stop(); shutil.rmtree(tmp, ignore_errors=True)
        os.environ.pop("POC_REMOTE_KEY", None)

    w = max(len(r[0]) for r in rows)
    for arm, v, obs in rows:
        print(f"{v:5} {arm.ljust(w)}  -- {obs}")
    fails = [r for r in rows if r[1] == "FAIL"]
    print(f"\n{len(rows) - len(fails)} PASS / {len(fails)} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
