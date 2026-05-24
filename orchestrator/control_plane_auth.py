"""Control-plane authentication for Perpetua-Tools operator APIs."""
from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any, Mapping

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

ENV_TOKEN = "ORAMA_CONTROL_PLANE_TOKEN"
ENV_INSECURE = "ORAMA_INSECURE_DEV"
DEFAULT_TOKEN_PATH = Path(".state/control_plane_token")

_SAFE_ROUTING_KEYS = (
    "distributed",
    "manager_endpoint",
    "manager_model",
    "manager_backend",
    "coder_endpoint",
    "coder_model",
    "coder_backend",
    "mac_reachable",
    "lmstudio_detected",
    "synced_at",
    "manager_affinity_alert",
)

_PUBLIC_PATHS = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})

_PROTECTED_GET_PREFIXES = (
    "/runtime",
    "/agents",
    "/activity",
    "/models",
    "/v1/jobs",
    "/user-input/status",
    "/user-input/next",
    "/budget",
    "/ecc/status",
    "/autoresearch/",
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


def _resolved_control_plane_token() -> str:
    token = control_plane_token()
    if token:
        return token
    if DEFAULT_TOKEN_PATH.is_file():
        return DEFAULT_TOKEN_PATH.read_text(encoding="utf-8").strip()
    return ""


def auth_headers() -> dict[str, str]:
    """Bearer headers for outbound PT HTTP clients (researchers, scripts)."""
    token = _resolved_control_plane_token()
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def auth_enforced() -> bool:
    """Return True when control-plane bearer auth must be checked.

    Auth is enforced when a token is configured, or when ORAMA_INSECURE_DEV is
    explicitly disabled (production mode). When neither is set, auth stays off so
    existing local stacks (start.sh, portal, launch_researchers) keep working
    until operators opt in with ORAMA_CONTROL_PLANE_TOKEN and/or
    ORAMA_INSECURE_DEV=0.
    """
    if control_plane_token():
        return True
    insecure = os.getenv(ENV_INSECURE, "").strip().lower()
    if insecure in ("1", "true", "yes"):
        return False
    if insecure in ("0", "false", "no"):
        return True
    return False


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
        return True
    if upper in ("GET", "HEAD"):
        return any(path.startswith(prefix) for prefix in _PROTECTED_GET_PREFIXES)
    return False


def persist_control_plane_token(token: str, path: Path | None = None) -> Path:
    token_path = path or DEFAULT_TOKEN_PATH
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(token, encoding="utf-8")
    token_path.chmod(0o600)
    return token_path


def ensure_control_plane_token() -> str:
    existing = control_plane_token()
    if existing:
        return existing
    if not auth_enforced():
        return ""
    generated = secrets.token_urlsafe(32)
    os.environ[ENV_TOKEN] = generated
    persist_control_plane_token(generated)
    return generated


def redact_runtime_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {"available": False, "gateway_ready": False, "distributed": False}
    gateway = payload.get("gateway") if isinstance(payload.get("gateway"), dict) else {}
    routing = payload.get("routing") if isinstance(payload.get("routing"), dict) else {}
    redacted: dict[str, Any] = {
        "available": True,
        "gateway_ready": bool(gateway.get("gateway_ready") or gateway.get("ready")),
        "distributed": bool(routing.get("distributed")),
        "gateway": {
            "gateway_ready": bool(gateway.get("gateway_ready") or gateway.get("ready")),
            "running": bool(gateway.get("running")),
            "port": int(gateway.get("port") or 0),
        },
        "routing": {key: routing[key] for key in _SAFE_ROUTING_KEYS if key in routing},
    }
    for key in _SAFE_ROUTING_KEYS:
        if key in routing:
            redacted[key] = routing[key]
    return redacted
