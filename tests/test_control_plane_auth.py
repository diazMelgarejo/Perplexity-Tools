#!/usr/bin/env python3
"""Control-plane auth regression tests for Perpetua-Tools."""
from __future__ import annotations

from fastapi.testclient import TestClient

from orchestrator.control_plane_auth import control_plane_auth_failure
from orchestrator.fastapi_app import app


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
