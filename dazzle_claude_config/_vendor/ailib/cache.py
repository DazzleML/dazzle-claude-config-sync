"""`run()` -- ask a backend through a cache.

The key is the backend's own identity plus the request's fingerprint plus
whatever facts the caller adds (a merge tool adds the three sides and its
rules; a diagnostic tool adds the event's stable fields), so the caller
never learns which backend facts matter for which transport. A hit
reproduces the response the backend gave, marked cached. Nothing is written
for a deferred or failed answer. A refresh skips the read and still writes.

A write also sweeps entries older than the TTL from the cache directory
under ANY file name: an entry that is never looked up again would otherwise
never expire.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .backend import Backend
from .types import Request, Response

CACHE_TTL_SECONDS = 24 * 60 * 60


def _now() -> float:            # a seam for tests
    return time.time()


def cache_key(backend: Backend, req: Request, extra: dict[str, Any] | None, tool: str) -> str:
    payload = json.dumps({"identity": backend.identity, "request": req.fingerprint(),
                          "extra": extra or {}, "tool": tool}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _path(cache_dir: Path, tool: str, backend: Backend, key: str) -> Path:
    return Path(cache_dir) / f"{tool}_{backend.spec.name or backend.spec.transport}_{key}.json"


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if _now() - float(data.get("cached_at", 0)) > CACHE_TTL_SECONDS:
            return None
        resp = data.get("response")
        if not isinstance(resp, dict) or not resp.get("text"):
            return None
        resp["cached_at"] = float(data["cached_at"])
        return resp
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _write(path: Path, backend: Backend, resp: Response) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {"cached_at": _now(), "identity": backend.identity,
                "response": {"text": resp.text, "model_used": resp.model_used,
                             "honoured": list(resp.honoured), "elapsed": resp.elapsed}}
        path.write_text(json.dumps(body, indent=1, default=str), encoding="utf-8")
    except OSError:
        pass                                             # a cache miss next time; not fatal


def _sweep(cache_dir: Path) -> None:
    cutoff = _now() - CACHE_TTL_SECONDS
    try:
        for p in Path(cache_dir).glob("*.json"):
            try:
                if float(json.loads(p.read_text(encoding="utf-8")).get("cached_at", 0)) < cutoff:
                    p.unlink()
            except (OSError, ValueError, TypeError, AttributeError):
                continue
    except OSError:
        pass


def run(backend: Backend, req: Request, *, cache_dir: Path | str,
        fingerprint_extra: dict[str, Any] | None = None, refresh: bool = False,
        tool: str = "ai") -> Response:
    """Ask `backend` for `req`, through the cache under `cache_dir`."""
    cache_dir = Path(cache_dir)
    key = cache_key(backend, req, fingerprint_extra, tool)
    path = _path(cache_dir, tool, backend, key)
    if not refresh:
        hit = _read(path)
        if hit:
            return Response("answered", text=hit["text"], model_used=hit.get("model_used", ""),
                            honoured=tuple(hit.get("honoured", ())), elapsed=float(hit.get("elapsed", 0)),
                            cached=True, cached_at=hit["cached_at"], key=key)
    resp = backend.invoke(req).with_(key=key)
    if resp.status == "answered":
        _write(path, backend, resp)
        _sweep(cache_dir)
    return resp
