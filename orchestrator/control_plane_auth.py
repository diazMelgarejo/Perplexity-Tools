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
_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TOKEN_PATH = _REPO_ROOT / ".state" / "control_plane_token"

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


def _read_persisted_token(path: Path | None = None) -> str:
    token_path = path or DEFAULT_TOKEN_PATH
    if token_path.is_file():
        return token_path.read_text(encoding="utf-8").strip()
    return ""


def _resolved_control_plane_token() -> str:
    token = control_plane_token()
    if token:
        return token
    return _read_persisted_token()


def auth_headers() -> dict[str, str]:
    """Bearer headers for outbound PT HTTP clients (researchers, scripts)."""
    token = _resolved_control_plane_token()
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def auth_enforced() -> bool:
    """
    Determine whether control-plane bearer authentication must be enforced.
    
    Enforcement rules:
    - Enforce when an explicit control-plane token is configured via environment or persisted file.
    - Do not enforce when `ORAMA_INSECURE_DEV` is set to `1`, `true`, or `yes` (case-insensitive).
    - Otherwise enforce by default (the system will auto-generate and persist a token).
    
    Returns:
        bool: `True` if authentication must be enforced, `False` otherwise.
    """
    if control_plane_token():
        return True
    insecure = os.getenv(ENV_INSECURE, "").strip().lower()
    if insecure in ("1", "true", "yes"):
        return False
    # Default: enforce. ensure_control_plane_token() will auto-generate.
    return True


def verify_control_plane_auth(request: Request) -> None:
    """
    Verify the incoming request's Authorization bearer token matches the configured control-plane token and raise on failure.
    
    If authentication enforcement is disabled, no check is performed.
    
    Parameters:
        request (Request): Incoming HTTP request whose "authorization" header will be validated against the expected bearer token.
    
    Raises:
        HTTPException: 503 if no control-plane token is configured; 401 if the Authorization header is missing or does not match `Bearer <token>`.
    """
    if not auth_enforced():
        return
    expected = _resolved_control_plane_token()
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
    persisted = _read_persisted_token()
    if persisted:
        os.environ[ENV_TOKEN] = persisted
        return persisted
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
