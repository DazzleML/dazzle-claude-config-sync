"""The subprocess transport: an executable, argv from a template, the
prompt on stdin. claude, codex, pi, gemini-cli -- one transport, different
argv. Nothing about a vendor lives here; a preset says which executable,
which flags, where the answer comes out.

Two properties a long-lived caller cannot do without, and a one-shot CLI
never notices: the child's working directory and environment are HANDED TO
THE CHILD (a fresh scratch directory, a copied environment with the
preset's `env_unset` removed) and never set on this process. A caller that
runs two backends, or lives longer than one call, sees no shared state.

**A populated working directory** (2026-09-09): when the Request names a
`workdir`, the child runs THERE instead of in the throwaway scratch, may
read and write there under the preset's `tools` grant (substituted into
the `{tools}` placeholder only then -- claude's `--allowedTools` list,
codex's `-s` sandbox mode), and the directory is left exactly as the child
left it for the caller to read back. The scratch is still made for the
call's own files (a schema, a prompt) and still removed. Measured before
this was built: `claude -p --allowedTools Read,Grep` refuses an edit and
`Read,Grep,Edit,Write` writes only inside the cwd; `codex exec -s
read-only` refuses and `-s workspace-write` writes only inside the cwd.

Carried from the transport's predecessors, because they were measured:
`env_unset` for the Claude Code CLI, which refuses to nest inside itself
while `CLAUDECODE` is set; executable candidates beyond PATH (npm and WinGet
shims for codex, `~/.local/bin` for claude); a `--version` check for a shim
that can point at a deleted binary; and the streaming reader with its
timeout/kill loop. The prompt always travels on stdin -- the argv length
limit that once forced a switch at 8000 bytes only ever applied to the argv
path, and both CLIs read stdin.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from ..types import MODEL, ON_PREM, SCHEMA, STREAM, TOOLS, Readiness, Request, Response, Spec

_PLACEHOLDERS = ("{model}", "{schema}", "{schema_file}", "{prompt_file}", "{output_file}", "{cwd}", "{tools}")


def find_exe(name: str, candidates: tuple[str, ...] = ()) -> str | None:
    """The executable to run: `name` if it is a path that exists, else PATH
    (with the `.exe` / `.cmd` variants `shutil.which` knows), else the first
    candidate that exists. A `.cmd` shim on Windows is run by full path."""
    if not name:
        return None
    p = Path(name).expanduser()
    if p.is_file():
        return str(p)
    hit = shutil.which(name) or (sys.platform == "win32" and (shutil.which(name + ".exe") or shutil.which(name + ".cmd")))
    if hit:
        return str(hit)
    for c in candidates:
        cp = Path(os.path.expandvars(c)).expanduser()
        if cp.is_file():
            return str(cp)
    return None


def _validated(exe: str) -> bool:
    """A shim can point at a deleted binary; `--version` proves it runs."""
    try:
        return subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10).returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


class SubprocessCli:
    """Stateless: every method takes the spec it is working for."""

    def capabilities(self, spec: Spec) -> frozenset[str]:
        caps = {STREAM}
        tpl = " ".join(spec.command)
        if "{model}" in tpl:
            caps.add(MODEL)
        if "{schema}" in tpl or "{schema_file}" in tpl:
            caps.add(SCHEMA)
        if "{tools}" in tpl and spec.tools:
            caps.add(TOOLS)
        if spec.on_prem:
            caps.add(ON_PREM)
        return frozenset(caps)

    def probe(self, spec: Spec) -> Readiness:
        name = spec.command[0] if spec.command else ""
        exe = find_exe(name, spec.candidates)
        if not exe:
            return Readiness(False, f"{name or '(no command)'} is not on PATH" + (f" -- {spec.hint}" if spec.hint else ""))
        if exe.lower().endswith((".cmd", ".bat")) and not _validated(exe):
            return Readiness(False, f"{exe} exists but does not run (a shim to a deleted binary?)")
        return Readiness(True, f"its CLI was found: {exe}")

    # -- argv -----------------------------------------------------------------------

    def _argv(self, spec: Spec, req: Request, exe: str, scratch: Path) -> tuple[list[str], dict, list[str]]:
        """The template substituted. An empty placeholder removes its own
        token AND the flag before it, so `--model {model}` with no model
        never becomes `--model ""` -- and `{tools}` is empty unless the
        request names a working directory, so a grant never reaches a call
        that gave the child nothing to work in. Returns (argv, files-made,
        honoured)."""
        values = {
            "{model}": spec.model,
            "{schema}": json.dumps(req.schema) if req.schema is not None else "",
            "{schema_file}": "", "{prompt_file}": "", "{output_file}": "",
            "{cwd}": req.workdir or str(scratch),
            "{tools}": spec.tools if req.workdir else "",
        }
        made: dict[str, Path] = {}
        tpl = " ".join(spec.command)
        if "{schema_file}" in tpl and req.schema is not None:
            made["schema"] = scratch / "schema.json"
            made["schema"].write_text(json.dumps(req.schema), encoding="utf-8")
            values["{schema_file}"] = str(made["schema"])
        if "{prompt_file}" in tpl:
            made["prompt"] = scratch / "prompt.md"
            made["prompt"].write_text(req.prompt, encoding="utf-8")
            values["{prompt_file}"] = str(made["prompt"])
        if "{output_file}" in tpl:
            made["output"] = scratch / "answer.out"
            values["{output_file}"] = str(made["output"])
        out: list[str] = [exe]
        used: set[str] = set()
        for tok in spec.command[1:]:
            holes = [h for h in _PLACEHOLDERS if h in tok]
            if not holes:
                out.append(tok)
                continue
            if any(values[h] == "" for h in holes):
                if out and out[-1].startswith("-") and out[-1] != exe:
                    out.pop()
                continue
            for h in holes:
                tok = tok.replace(h, values[h])
                used.add(h)
            out.append(tok)
        honoured = []
        if "{model}" in used and spec.model:
            honoured.append(MODEL)
        if ({"{schema}", "{schema_file}"} & used) and req.schema is not None:
            honoured.append(SCHEMA)
        if "{tools}" in used:
            honoured.append(TOOLS)
        return out, made, honoured

    # -- running ----------------------------------------------------------------------

    def invoke(self, spec: Spec, req: Request) -> Response:
        name = spec.command[0] if spec.command else ""
        exe = find_exe(name, spec.candidates)
        if not exe:
            return Response("failed", error=f"{name or '(no command)'} is not on PATH")
        scratch = Path(tempfile.mkdtemp(prefix="ailib-cli-"))
        # The child's cwd: the caller's working directory when the request
        # names one (kept afterwards, it is theirs), else the scratch.
        cwd = Path(req.workdir) if req.workdir else scratch
        try:
            argv, made, honoured = self._argv(spec, req, exe, scratch)
            env = dict(os.environ)
            for k in spec.env_unset:
                env.pop(k, None)
            stdin = None if "prompt" in made else req.prompt
            started = time.monotonic()
            try:
                if req.stream_to is not None:
                    rc, out, err = self._stream(argv, env, cwd, stdin, req)
                    honoured.append(STREAM)
                else:
                    p = subprocess.run(argv, input=stdin, capture_output=True, text=True,
                                       encoding="utf-8", errors="replace", timeout=req.timeout,
                                       cwd=str(cwd), env=env)
                    rc, out, err = p.returncode, p.stdout, p.stderr
            except subprocess.TimeoutExpired:
                return Response("failed", error=f"{name} timed out after {req.timeout}s")
            except (FileNotFoundError, OSError) as e:
                return Response("failed", error=f"cannot run {exe}: {e}")
            elapsed = time.monotonic() - started
            if rc != 0:
                detail = (err or out or "").strip()
                return Response("failed", elapsed=elapsed,
                                error=f"{name} exited with code {rc}" + (f": {detail[:400]}" if detail else ""))
            text, why = self._locate(spec, out, made)
            if why:
                return Response("failed", error=why, elapsed=elapsed)
            return Response("answered", text=text, model_used=spec.model, honoured=tuple(honoured),
                            elapsed=elapsed)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def _locate(self, spec: Spec, stdout: str, made: dict[str, Path]) -> tuple[str, str]:
        """Where the answer is, per `Spec.answer`."""
        where = spec.answer or "stdout"
        if where == "stdout":
            return stdout, ""
        if where.startswith("stdout-json:"):
            key = where.split(":", 1)[1]
            body = stdout.strip()
            try:
                obj = json.loads(body)
            except ValueError:
                try:                                         # a chatty CLI: the last line
                    obj = json.loads(body.splitlines()[-1]) if body else None
                except ValueError:
                    obj = None
            if not isinstance(obj, dict):
                return "", f"{spec.command[0]} did not print a JSON envelope on stdout"
            if key not in obj:
                return "", f"the JSON envelope has no key {key!r} (it has: {', '.join(obj)})"
            val = obj[key]
            return (val if isinstance(val, str) else json.dumps(val)), ""
        if where.startswith("file:"):
            path = made.get("output")
            if path is None:
                return "", "answer is 'file:{output_file}' but the template has no {output_file}"
            try:
                return path.read_text(encoding="utf-8"), ""
            except OSError as e:
                return "", f"{spec.command[0]} wrote no answer file: {e}"
        return "", f"unknown answer locator {where!r}"

    def _stream(self, argv, env, cwd, stdin, req: Request):
        """Echo the child's output to `req.stream_to` as it arrives, with the
        timeout enforced by polling; returns (rc, output, '')."""
        proc = subprocess.Popen(argv, env=env, cwd=str(cwd),
                                stdin=subprocess.PIPE if stdin is not None else None,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
        if stdin is not None:
            proc.stdin.write(stdin)
            proc.stdin.close()
        lines: list[str] = []

        def _reader():
            for line in proc.stdout:
                lines.append(line)
                try:
                    req.stream_to.write(line)
                    req.stream_to.flush()
                except (OSError, ValueError):
                    pass

        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        start = time.monotonic()
        while proc.poll() is None:
            if time.monotonic() - start > req.timeout:
                proc.kill()
                proc.wait()
                raise subprocess.TimeoutExpired(argv, req.timeout)
            time.sleep(0.05)
        t.join(timeout=5)
        return proc.returncode, "".join(lines), ""
