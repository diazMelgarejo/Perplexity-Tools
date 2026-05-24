"""Control-plane authentication for Perpetua-Tools operator APIs."""
from __future__ import annotations

import os
import secrets
from typing import Any, Mapping

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

ENV_TOKEN = "ORAMA_CONTROL_PLANE_TOKEN"
ENV_INSECURE = "ORAMA_INSECURE_DEV"

_PUBLIC_PATHS = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})

_PROTECTED_GET_PREFIXES = (
    "/runtime",
    "/agents",
    "/activity",
    "/models",
    "/v1/jobs",
    "/user-input/status",
    "/budget",
    "/ecc/status",
)

_PROTECTED_POST_PREFIXES = (
    "/user-input",
    "/runtime/bootstrap",
    "/orchestrate",
    "/v1/jobs",
    "/ecc/sync",
    "/autoresearch/",
)


def control_plane_token() -> str:
    return os.getenv(ENV_TOKEN, "").strip()


def auth_enforced() -> bool:
    if control_plane_token():
        return True
    return os.getenv(ENV_INSECURE, "").strip().lower() not in ("1", "true", "yes")


def verify_control_plane_auth(request: Request) -> None:
    if not auth_enforced():
        return
    expected = control_plane_token()
    if not expected:
        raise HTTPException(status_code=503, detail="Control plane token not configured")
    auth_header = request.headers.get("authorization", "")
    if auth_header == f"Bearer {expected}":
        return
    raise HTTPException(status_code=401, detail="Unauthorized")


def control_plane_auth_failure(request: Request) -> JSONResponse | None:
    if not auth_enforced():
        return None
    try:
        verify_control_plane_auth(request)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return None


def pt_path_requires_auth(path: str, method: str) -> bool:
    if path in _PUBLIC_PATHS:
        return False
    if method.upper() == "OPTIONS":
        return False
    upper = method.upper()
    if upper in ("POST", "PUT", "PATCH", "DELETE"):
        return not path.startswith("/user-input/next")
    if upper == "GET":
        return any(path.startswith(prefix) for prefix in _PROTECTED_GET_PREFIXES)
    return False


def ensure_control_plane_token() -> str:
    existing = control_plane_token()
    if existing:
        return existing
    if not auth_enforced():
        return ""
    generated = secrets.token_urlsafe(32)
    os.environ[ENV_TOKEN] = generated
    return generated


def redact_runtime_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {"available": False, "gateway_ready": False, "distributed": False}
    gateway = payload.get("gateway") if isinstance(payload.get("gateway"), dict) else {}
    routing = payload.get("routing") if isinstance(payload.get("routing"), dict) else {}
    return {
        "available": True,
        "gateway_ready": bool(gateway.get("gateway_ready") or gateway.get("ready")),
        "distributed": bool(routing.get("distributed")),
    }
