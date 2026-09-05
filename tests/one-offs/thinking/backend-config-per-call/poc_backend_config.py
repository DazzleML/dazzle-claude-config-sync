"""POC: can a backend take its configuration PER CALL instead of from module globals?

Written 2026-09-05, before the upstream contribution is proposed, to settle
whether the shape is viable rather than to argue about it.

THE PROPOSAL
    The vendored library's contract is `invoke(prompt, verbose, timeout)`,
    with nowhere to pass configuration, so every backend keeps its settings
    in module globals (`lmstudio._endpoint/_model/_schema`,
    `prompt_only._output_dir`) and the facade sets a global then immediately
    calls. The proposal is `invoke(prompt, *, verbose, timeout, config=None)`
    -- a plain immutable mapping per call, no module state.

PREDICTIONS, written before building
    P1 (control, predicted to FAIL i.e. to contaminate): with today's global
       state, two callers that each configure a different endpoint and model
       and then invoke can send each other's model. Predicted: at least one
       request arrives at the wrong server, or with the wrong model.
    P2 (experimental, predicted to hold): with configuration passed per call,
       the same interleaving sends each caller's own model to each caller's
       own server. Predicted: zero cross-contamination.

PASS CRITERIA, written before running
    Control:      >= 1 of 2 requests carries a model or endpoint belonging to
                  the other caller.  (If it does NOT, the instrument cannot
                  detect the defect and NOTHING here may be reported as
                  evidence -- see the method-broken exit.)
    Experimental: exactly 2 requests, each carrying its own caller's model,
                  and each arriving at its own caller's server. Zero crossed.

FALLBACK if the control does not contaminate
    The note says the global state is a LATENT hazard rather than a live one,
    and the upstream contribution is justified by the other two tells (the
    test fixture that must reset globals; the health check that mutated what
    it reported on) rather than by concurrency.

HONEST SCOPE
    The interleaving below is FORCED with events, not observed in the wild.
    ccs today runs one merge at a time in one process, so this demonstrates
    that the SHAPE permits cross-talk, not that ccs currently suffers it.
    That distinction belongs in any note that cites this.

    Fake servers only (stdlib http.server, ephemeral ports). No hosted CLI is
    called; nothing reads the maintainer's real configuration; nothing depends
    on the local LM Studio server, which is being shut down.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))

from dazzle_claude_config._vendor.ailib.backends import lmstudio  # noqa: E402

ANSWER = json.dumps({"hunks": []})


class _Recorder(BaseHTTPRequestHandler):
    """A fake model server that records the model each request asked for."""

    def log_message(self, *a):
        pass

    def _json(self, body):
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.startswith("/api/v0/models"):
            self._json({"data": [{"id": m, "state": "loaded",
                                  "loaded_context_length": 8192}
                                 for m in self.server.models]})
        else:
            self._json({"data": [{"id": m} for m in self.server.models]})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n).decode())
        self.server.asked.append(body.get("model"))
        self._json({"choices": [{"message": {"content": ANSWER}}]})


def start_server(models):
    srv = HTTPServer(("127.0.0.1", 0), _Recorder)
    srv.models = models
    srv.asked = []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# -- the arms ----------------------------------------------------------------

def control_arm(a, b):
    """TODAY's design: configure() writes module globals, then invoke reads them.

    The interleaving is forced so the race is deterministic rather than
    flaky: caller 1 configures, caller 2 configures, THEN caller 1 invokes.
    """
    one_configured = threading.Event()
    two_configured = threading.Event()
    sent = {}

    def caller_one():
        lmstudio.configure(endpoint=f"http://127.0.0.1:{a.server_port}/v1",
                           model="model-ONE", schema=None)
        one_configured.set()
        two_configured.wait(5)              # let the other caller configure
        ok, _ = lmstudio.invoke("prompt from caller one", timeout=10)
        sent["one"] = ok

    def caller_two():
        one_configured.wait(5)
        lmstudio.configure(endpoint=f"http://127.0.0.1:{b.server_port}/v1",
                           model="model-TWO", schema=None)
        two_configured.set()

    t1 = threading.Thread(target=caller_one)
    t2 = threading.Thread(target=caller_two)
    t1.start(); t2.start(); t1.join(10); t2.join(10)
    return sent


# -- the proposed shape ------------------------------------------------------
# A faithful transposition of the parts of lmstudio.py that read configuration:
# resolve which model to ask for, then post. No module state is read or
# written. Everything else in the real module (the load-state guard, the
# context-window check, the error handling) is untouched by the proposal and
# is deliberately NOT reimplemented here -- this is an argument about where
# configuration lives, not a rewrite.

def variant_invoke(prompt, *, config, timeout=120):
    endpoint = config["endpoint"].rstrip("/")
    want = config.get("model") or ""
    with urllib.request.urlopen(
            urllib.request.Request(endpoint + "/models",
                                   headers={"Accept": "application/json"}),
            timeout=timeout) as r:
        listed = [d["id"] for d in json.loads(r.read().decode())["data"]]
    model = want or listed[0]
    if model not in listed:
        return False, f"model {model!r} is not on {endpoint}"
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "temperature": 0, "stream": False, "reasoning_effort": "none"}
    if config.get("schema") is not None:
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": "answer", "strict": True,
                                                   "schema": config["schema"]}}
    req = urllib.request.Request(endpoint + "/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        answer = json.loads(r.read().decode())
    return True, (answer["choices"][0]["message"]["content"] or "")


def experimental_arm(a, b):
    """The proposal: each caller carries its own configuration into the call."""
    one_ready = threading.Event()
    two_ready = threading.Event()

    def caller_one():
        cfg = {"endpoint": f"http://127.0.0.1:{a.server_port}/v1", "model": "model-ONE"}
        one_ready.set()
        two_ready.wait(5)                   # the SAME interleaving as the control
        variant_invoke("prompt from caller one", config=cfg, timeout=10)

    def caller_two():
        one_ready.wait(5)
        cfg = {"endpoint": f"http://127.0.0.1:{b.server_port}/v1", "model": "model-TWO"}
        two_ready.set()
        variant_invoke("prompt from caller two", config=cfg, timeout=10)

    t1 = threading.Thread(target=caller_one)
    t2 = threading.Thread(target=caller_two)
    t1.start(); t2.start(); t1.join(10); t2.join(10)


def main():
    print(__doc__.split("HONEST SCOPE")[0].strip())
    print("=" * 72)

    # --- control -----------------------------------------------------------
    a = start_server(["model-ONE"])
    b = start_server(["model-TWO"])
    control_arm(a, b)
    ctl_a, ctl_b = list(a.asked), list(b.asked)
    print(f"\nCONTROL (today's module globals)")
    print(f"  server A (caller one's own) was asked for: {ctl_a}")
    print(f"  server B (caller two's own) was asked for: {ctl_b}")
    crossed = ("model-TWO" in ctl_a) or ("model-TWO" in ctl_b and not ctl_a)
    contaminated = bool(ctl_b) and not ctl_a      # caller one's request landed on B
    print(f"  caller one's request went to the WRONG server: {contaminated}")
    print(f"  a request carried the WRONG model: {crossed}")
    control_failed = contaminated or crossed
    print(f"  -> control {'CONTAMINATED as predicted' if control_failed else 'did NOT contaminate'}")
    a.shutdown(); b.shutdown()

    if not control_failed:
        print("\nVERDICT: method-broken / premise unsupported -- the instrument could not "
              "produce contamination, so nothing below is evidence. See the fallback.")
        return 2

    # --- experimental ------------------------------------------------------
    a2 = start_server(["model-ONE"])
    b2 = start_server(["model-TWO"])
    experimental_arm(a2, b2)
    ex_a, ex_b = list(a2.asked), list(b2.asked)
    print(f"\nEXPERIMENTAL (configuration passed per call)")
    print(f"  server A was asked for: {ex_a}")
    print(f"  server B was asked for: {ex_b}")
    clean = ex_a == ["model-ONE"] and ex_b == ["model-TWO"]
    print(f"  -> each caller reached its own server with its own model: {clean}")
    a2.shutdown(); b2.shutdown()

    print("\n" + "=" * 72)
    if control_failed and clean:
        print("VERDICT: survived -- the shape carries per-call configuration without "
              "cross-talk, and the control proves the instrument can see cross-talk.")
        return 0
    print("VERDICT: refuted -- the per-call shape did not keep the callers apart.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
