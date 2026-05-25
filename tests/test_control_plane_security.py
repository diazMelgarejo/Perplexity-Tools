"""Tests for control-plane auth and memory redaction (security fixes 1–3)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from orchestrator.fastapi_app import app
from orchestrator.memory_governance import classify_and_redact
from orchestrator.redaction import contains_secret, redact_text


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "0")
    monkeypatch.setenv("ORAMA_CONTROL_PLANE_TOKEN", "pt-test-token")
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_health_public_when_auth_enforced(client):
    response = client.get("/health")
    assert response.status_code == 200


def test_v1_jobs_requires_bearer(client):
    denied = client.post("/v1/jobs", json={"prompt": "hello", "intent": "freeform"})
    allowed = client.post(
        "/v1/jobs",
        json={"prompt": "hello", "intent": "freeform"},
        headers={"Authorization": "Bearer pt-test-token"},
    )
    assert denied.status_code == 401
    assert allowed.status_code in (200, 400)


def test_redact_google_api_key():
    raw = '{"apiKey": "AIzaSy0123456789012345678901234567890"}'
    redacted = redact_text(raw)
    assert "AIzaSy" not in redacted
    assert contains_secret(raw) is True
    assert contains_secret(redacted) is False


def test_classify_and_redact_strips_prompt_secrets():
    payload = {
        "prompt": "use key AIzaSy0123456789012345678901234567890",
        "role": "coder",
    }
    safe, memory_class = classify_and_redact(payload, event_type="dispatch")
    assert memory_class == "prompt"
    assert "AIzaSy" not in json.dumps(safe)
    assert safe["_memory_class"] == "prompt"
