#!/usr/bin/env python3
"""Control-plane auth regression tests for Perpetua-Tools."""
from __future__ import annotations

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


def test_default_stack_without_auth_env_allows_operator_routes(monkeypatch):
    monkeypatch.delenv("ORAMA_INSECURE_DEV", raising=False)
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)

    with TestClient(app, raise_server_exceptions=False) as client:
        agents = client.get("/agents")
        queued = client.post("/user-input", json={"message": "hello"})

    assert agents.status_code == 200
    assert queued.status_code == 200


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
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.delenv("ORAMA_INSECURE_DEV", raising=False)
    assert auth_enforced() is False

    monkeypatch.setenv("ORAMA_CONTROL_PLANE_TOKEN", "secret")
    assert auth_enforced() is True

    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "1")
    assert auth_enforced() is False

    monkeypatch.setenv("ORAMA_INSECURE_DEV", "0")
    assert auth_enforced() is True


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
