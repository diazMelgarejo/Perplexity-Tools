#!/usr/bin/env python3
"""Control-plane auth regression tests for Perpetua-Tools."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from orchestrator.control_plane_auth import (
    auth_enforced,
    control_plane_auth_failure,
    redact_runtime_payload,
)
from orchestrator.fastapi_app import app


def test_user_input_next_requires_token_when_enforced(monkeypatch):
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "0")
    monkeypatch.setenv("ORAMA_CONTROL_PLANE_TOKEN", "pt-test-token")

    with TestClient(app, raise_server_exceptions=False) as client:
        client.post(
            "/user-input",
            json={"message": "steal-me"},
            headers={"Authorization": "Bearer pt-test-token"},
        )
        denied = client.get("/user-input/next")
        allowed = client.get(
            "/user-input/next",
            headers={"Authorization": "Bearer pt-test-token"},
        )

    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json().get("message", {}).get("message") == "steal-me"


def test_user_input_requires_token_when_enforced(monkeypatch):
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "0")
    monkeypatch.setenv("ORAMA_CONTROL_PLANE_TOKEN", "pt-test-token")

    with TestClient(app, raise_server_exceptions=False) as client:
        denied = client.post("/user-input", json={"message": "hello"})
        allowed = client.post(
            "/user-input",
            json={"message": "hello"},
            headers={"Authorization": "Bearer pt-test-token"},
        )

    assert denied.status_code == 401
    assert allowed.status_code == 200


def test_control_plane_auth_failure_helper(monkeypatch):
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "0")
    monkeypatch.setenv("ORAMA_CONTROL_PLANE_TOKEN", "pt-test-token")

    class _Req:
        headers: dict[str, str] = {}

    denied = control_plane_auth_failure(_Req())
    assert denied is not None
    assert denied.status_code == 401


def test_default_stack_without_auth_env_enforces_auth_on_operator_routes(monkeypatch):
    """Secure-by-default (2026-05-28): no env vars → auth ENFORCED.

    Previously this test asserted that unauthenticated routes returned 200; the
    pre-v1 security audit flipped the default so a fresh deployment auto-
    generates a token. Local stacks that need the old behaviour must explicitly
    set ORAMA_INSECURE_DEV=1 (see test below).
    """
    monkeypatch.delenv("ORAMA_INSECURE_DEV", raising=False)
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)

    with TestClient(app, raise_server_exceptions=False) as client:
        agents = client.get("/agents")
        queued = client.post("/user-input", json={"message": "hello"})

    assert agents.status_code == 401, "operator route must require auth by default"
    assert queued.status_code == 401, "operator route must require auth by default"


def test_explicit_insecure_dev_opens_operator_routes(monkeypatch, tmp_path):
    """ORAMA_INSECURE_DEV=1 is the only path back to the prior insecure default."""
    # Point DEFAULT_TOKEN_PATH at a non-existent temp file so a previously
    # persisted .state/control_plane_token from another test does not bleed in
    # (control_plane_token() would otherwise lift it back into env and re-enable auth).
    monkeypatch.setattr(
        "orchestrator.control_plane_auth.DEFAULT_TOKEN_PATH",
        tmp_path / "no_token",
    )
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "1")
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)

    with TestClient(app, raise_server_exceptions=False) as client:
        agents = client.get("/agents")

    assert agents.status_code == 200


def test_persisted_token_reused_on_restart_without_env(monkeypatch, tmp_path):
    token_path = tmp_path / "control_plane_token"
    token_path.write_text("persisted-token", encoding="utf-8")
    monkeypatch.setattr(
        "orchestrator.control_plane_auth.DEFAULT_TOKEN_PATH",
        token_path,
    )
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "0")
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)

    from orchestrator.control_plane_auth import ensure_control_plane_token

    token = ensure_control_plane_token()

    assert token == "persisted-token"
    assert token_path.read_text(encoding="utf-8") == "persisted-token"


def test_bearer_from_persisted_file_accepted_when_enforced(monkeypatch, tmp_path):
    token_path = tmp_path / "control_plane_token"
    token_path.write_text("file-only-token", encoding="utf-8")
    monkeypatch.setattr(
        "orchestrator.control_plane_auth.DEFAULT_TOKEN_PATH",
        token_path,
    )
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "0")
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)

    with TestClient(app, raise_server_exceptions=False) as client:
        allowed = client.get(
            "/agents",
            headers={"Authorization": "Bearer file-only-token"},
        )

    assert allowed.status_code == 200


def test_production_mode_without_token_auto_generates_and_requires_bearer(monkeypatch, tmp_path):
    token_path = tmp_path / "control_plane_token"
    monkeypatch.setattr(
        "orchestrator.control_plane_auth.DEFAULT_TOKEN_PATH",
        token_path,
    )
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "0")
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)

    with TestClient(app, raise_server_exceptions=False) as client:
        denied = client.get("/agents")
        token = token_path.read_text(encoding="utf-8")
        allowed = client.get("/agents", headers={"Authorization": f"Bearer {token}"})

    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert token


def test_head_on_protected_route_requires_auth_when_enforced(monkeypatch):
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "0")
    monkeypatch.setenv("ORAMA_CONTROL_PLANE_TOKEN", "pt-test-token")

    with TestClient(app, raise_server_exceptions=False) as client:
        denied = client.head("/agents")

    assert denied.status_code == 401


def test_auth_enforced_matrix(monkeypatch):
    """Matrix reflects secure-by-default behavior (changed 2026-05-28)."""
    # Case 1: no env vars → ENFORCE (was: skip)
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.delenv("ORAMA_INSECURE_DEV", raising=False)
    assert auth_enforced() is True

    # Case 2: token configured → ENFORCE
    monkeypatch.setenv("ORAMA_CONTROL_PLANE_TOKEN", "secret")
    assert auth_enforced() is True

    # Case 3: ORAMA_INSECURE_DEV=1 → SKIP (explicit opt-out)
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "1")
    assert auth_enforced() is False

    # Case 4: ORAMA_INSECURE_DEV=0 → ENFORCE
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "0")
    assert auth_enforced() is True


def test_auth_enforced_insecure_dev_true_alias(monkeypatch):
    """ORAMA_INSECURE_DEV='true' (word form) must also disable auth enforcement."""
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "true")
    assert auth_enforced() is False


def test_auth_enforced_insecure_dev_yes_alias(monkeypatch):
    """ORAMA_INSECURE_DEV='yes' must also disable auth enforcement."""
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "yes")
    assert auth_enforced() is False


def test_auth_enforced_insecure_dev_true_uppercase(monkeypatch):
    """ORAMA_INSECURE_DEV value is case-insensitive — 'TRUE' must disable auth."""
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "TRUE")
    assert auth_enforced() is False


def test_auth_enforced_insecure_dev_yes_uppercase(monkeypatch):
    """ORAMA_INSECURE_DEV='YES' must disable auth (case-insensitive)."""
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "YES")
    assert auth_enforced() is False


def test_auth_enforced_insecure_dev_false_alias(monkeypatch):
    """ORAMA_INSECURE_DEV='false' → production mode → auth ENFORCED."""
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "false")
    assert auth_enforced() is True


def test_auth_enforced_insecure_dev_no_alias(monkeypatch):
    """ORAMA_INSECURE_DEV='no' → production mode → auth ENFORCED."""
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "no")
    assert auth_enforced() is True


def test_auth_enforced_insecure_dev_with_whitespace(monkeypatch):
    """ORAMA_INSECURE_DEV=' 1 ' (padded) must disable auth (strip() applied)."""
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.setenv("ORAMA_INSECURE_DEV", " 1 ")
    assert auth_enforced() is False


def test_auth_enforced_insecure_wins_over_token_env_var(monkeypatch):
    """ORAMA_INSECURE_DEV=1 takes precedence over ORAMA_CONTROL_PLANE_TOKEN in env."""
    monkeypatch.setenv("ORAMA_CONTROL_PLANE_TOKEN", "super-secret-token")
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "1")
    assert auth_enforced() is False


def test_auth_enforced_order_insecure_checked_before_token(monkeypatch):
    """Priority: ORAMA_INSECURE_DEV is evaluated before control_plane_token().

    This test documents and guards the evaluation order introduced in the
    2026-05-28 audit: insecure flag is checked first so that ops can always
    disable enforcement on a box that already has a persisted token.
    """
    monkeypatch.setenv("ORAMA_CONTROL_PLANE_TOKEN", "any-token")
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "yes")
    # Insecure takes priority — auth must be disabled despite token being set.
    assert auth_enforced() is False


def test_auth_enforced_unknown_insecure_value_defaults_to_enforce(monkeypatch):
    """An unrecognised ORAMA_INSECURE_DEV value (e.g. 'maybe') → ENFORCE (secure default)."""
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "maybe")
    # Falls through both 'if insecure in (...)' branches; reaches default True.
    assert auth_enforced() is True


def test_default_no_env_returns_503_when_no_token_configured(monkeypatch, tmp_path):
    """Without ORAMA_INSECURE_DEV and with no persisted token, a request must
    get 503 (token not configured) rather than silently 200.

    This is the new secure-by-default behaviour; prior behaviour returned 200.
    """
    monkeypatch.setattr(
        "orchestrator.control_plane_auth.DEFAULT_TOKEN_PATH",
        tmp_path / "no_token_here",
    )
    monkeypatch.delenv("ORAMA_INSECURE_DEV", raising=False)
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/agents")

    # Auth is enforced; token not configured → 503 or 401 (depends on
    # ensure_control_plane_token() auto-generation; either is not 200).
    assert resp.status_code in (401, 503), (
        f"Expected 401 or 503 for unauthenticated request, got {resp.status_code}"
    )


def test_redact_runtime_payload_preserves_routing_summary():
    payload = {
        "credentials": {"has_api_key": True},
        "gateway": {"gateway_ready": True, "openclaw_config": {"auth": "secret"}},
        "routing": {
            "distributed": True,
            "manager_endpoint": "http://127.0.0.1:11434",
            "manager_model": "qwen3.5:9b-nvfp4",
        },
    }

    redacted = redact_runtime_payload(payload)

    assert "credentials" not in redacted
    assert "openclaw_config" not in redacted.get("gateway", {})
    assert redacted["distributed"] is True
    assert redacted["manager_endpoint"] == "http://127.0.0.1:11434"
    assert redacted["routing"]["manager_model"] == "qwen3.5:9b-nvfp4"


def test_redact_runtime_payload_empty():
    assert redact_runtime_payload(None) == {
        "available": False,
        "gateway_ready": False,
        "distributed": False,
    }


# ── auth_enforced() edge cases (secure-by-default, 2026-05-28) ───────────────

def test_auth_enforced_insecure_dev_true(monkeypatch):
    """ORAMA_INSECURE_DEV=true (string) must disable enforcement."""
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "true")
    assert auth_enforced() is False


def test_auth_enforced_insecure_dev_yes(monkeypatch):
    """ORAMA_INSECURE_DEV=yes must disable enforcement."""
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "yes")
    assert auth_enforced() is False


def test_auth_enforced_insecure_dev_false_enforces(monkeypatch):
    """ORAMA_INSECURE_DEV=false must NOT disable enforcement (not in opt-out set)."""
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "false")
    assert auth_enforced() is True


def test_auth_enforced_insecure_dev_no_enforces(monkeypatch):
    """ORAMA_INSECURE_DEV=no must NOT disable enforcement (not in opt-out set)."""
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "no")
    assert auth_enforced() is True


def test_auth_enforced_insecure_dev_whitespace_normalised(monkeypatch):
    """ORAMA_INSECURE_DEV with surrounding whitespace must strip before comparison."""
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "  1  ")
    assert auth_enforced() is False


def test_auth_enforced_insecure_dev_empty_string_enforces(monkeypatch):
    """Empty ORAMA_INSECURE_DEV must fall through to the secure default (enforce)."""
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "")
    assert auth_enforced() is True


def test_auth_enforced_insecure_dev_wins_over_token(monkeypatch):
    """ORAMA_INSECURE_DEV=1 explicitly disables auth even when a token is configured.

    Updated per PR #56 (fix: honor ORAMA_INSECURE_DEV when persisted token exists).
    Previously the token check ran first and silently re-enabled auth even when
    the operator had explicitly opted into insecure-dev mode. The new contract:
    INSECURE_DEV is an explicit user-intent override and always wins.
    """
    monkeypatch.setenv("ORAMA_CONTROL_PLANE_TOKEN", "some-token")
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "1")
    # INSECURE_DEV check happens first now — auth must be disabled
    assert auth_enforced() is False


# ── verify_control_plane_auth 503 when no token configured ───────────────────

def test_verify_control_plane_auth_503_when_auth_enforced_but_no_token(
    monkeypatch, tmp_path
):
    """verify_control_plane_auth raises HTTP 503 when auth is enforced but no
    token is available (neither env nor persisted file).

    This guards against the window between first startup and token generation,
    or a misconfigured deployment where ensure_control_plane_token was not
    called.
    """
    monkeypatch.setattr(
        "orchestrator.control_plane_auth.DEFAULT_TOKEN_PATH",
        tmp_path / "no_token",
    )
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.delenv("ORAMA_INSECURE_DEV", raising=False)

    from orchestrator.control_plane_auth import verify_control_plane_auth
    from fastapi import HTTPException

    class _FakeRequest:
        headers: dict = {}

    with pytest.raises(HTTPException) as exc_info:
        verify_control_plane_auth(_FakeRequest())

    assert exc_info.value.status_code == 503


def test_default_stack_no_token_file_enforces_auth(monkeypatch, tmp_path):
    """Regression: a fresh deployment with no token file must still enforce auth.

    Previously the fallback was to allow access; now both env and file absent
    must result in 401 (503 at verify time, surfaced as 401 or 503 via the app).
    """
    monkeypatch.setattr(
        "orchestrator.control_plane_auth.DEFAULT_TOKEN_PATH",
        tmp_path / "no_token",
    )
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.delenv("ORAMA_INSECURE_DEV", raising=False)

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/agents")

    assert resp.status_code in (401, 503), (
        f"Expected 401 or 503 for unauthenticated request with no token configured, got {resp.status_code}"
    )
