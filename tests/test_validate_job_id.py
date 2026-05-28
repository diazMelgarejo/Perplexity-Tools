"""Tests for the job_id path-traversal guard introduced in fastapi_app.py.

Covers:
  - _validate_job_id() unit tests (UUID4 regex acceptance/rejection)
  - HTTP-level tests for /v1/jobs/{job_id} endpoints (GET, cancel, replay)
    confirming 400 for malformed IDs and updated 404 message for unknown IDs.

Security context: job_id flows into filesystem paths (.state/jobs/<id>/result.json).
Any deviation from uuid4 format at the HTTP boundary must be rejected with 400
before it reaches disk I/O.

Reference: fastapi_app.py _UUID4_RE, _validate_job_id (added 2026-05-28 v1 audit)
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from orchestrator.fastapi_app import _validate_job_id, app


# ── _validate_job_id unit tests ───────────────────────────────────────────────

def test_validate_job_id_accepts_lowercase_uuid4():
    """A canonical lowercase uuid4 string must pass without raising."""
    valid_id = str(uuid.uuid4())
    result = _validate_job_id(valid_id)
    assert result == valid_id


def test_validate_job_id_accepts_uppercase_uuid4():
    """The regex uses IGNORECASE; uppercase UUID4 must also be accepted."""
    valid_id = str(uuid.uuid4()).upper()
    result = _validate_job_id(valid_id)
    assert result == valid_id


def test_validate_job_id_accepts_mixed_case_uuid4():
    """Mixed-case UUID4 string must be accepted."""
    raw = str(uuid.uuid4())
    mixed = raw.swapcase()
    result = _validate_job_id(mixed)
    assert result == mixed


def test_validate_job_id_rejects_path_traversal_dotdot():
    """Path traversal via '..' must be rejected with HTTP 400."""
    with pytest.raises(HTTPException) as exc_info:
        _validate_job_id("../etc/passwd")
    assert exc_info.value.status_code == 400


def test_validate_job_id_rejects_path_traversal_nested():
    """Nested path traversal payload must be rejected with HTTP 400."""
    with pytest.raises(HTTPException) as exc_info:
        _validate_job_id("../../jobs/secret")
    assert exc_info.value.status_code == 400


def test_validate_job_id_rejects_absolute_path():
    """Absolute path as job_id must be rejected with HTTP 400."""
    with pytest.raises(HTTPException) as exc_info:
        _validate_job_id("/etc/passwd")
    assert exc_info.value.status_code == 400


def test_validate_job_id_rejects_empty_string():
    """Empty string is not a valid UUID4 and must be rejected with HTTP 400."""
    with pytest.raises(HTTPException) as exc_info:
        _validate_job_id("")
    assert exc_info.value.status_code == 400


def test_validate_job_id_rejects_random_garbage():
    """Arbitrary non-UUID strings must be rejected with HTTP 400."""
    for bad in ["not-a-uuid", "12345", "hello world", "'; DROP TABLE jobs;--"]:
        with pytest.raises(HTTPException) as exc_info:
            _validate_job_id(bad)
        assert exc_info.value.status_code == 400, f"Expected 400 for {bad!r}"


def test_validate_job_id_rejects_uuid1():
    """UUID version 1 is not a UUID4 and must be rejected (version nibble check)."""
    uuid1_id = str(uuid.uuid1())
    with pytest.raises(HTTPException) as exc_info:
        _validate_job_id(uuid1_id)
    assert exc_info.value.status_code == 400


def test_validate_job_id_rejects_uuid3():
    """UUID version 3 is not UUID4 and must be rejected."""
    uuid3_id = str(uuid.uuid3(uuid.NAMESPACE_DNS, "example.com"))
    with pytest.raises(HTTPException) as exc_info:
        _validate_job_id(uuid3_id)
    assert exc_info.value.status_code == 400


def test_validate_job_id_rejects_uuid5():
    """UUID version 5 is not UUID4 and must be rejected."""
    uuid5_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "example.com"))
    with pytest.raises(HTTPException) as exc_info:
        _validate_job_id(uuid5_id)
    assert exc_info.value.status_code == 400


def test_validate_job_id_returns_same_value():
    """_validate_job_id must return the original job_id string on success."""
    job_id = str(uuid.uuid4())
    assert _validate_job_id(job_id) is job_id


def test_validate_job_id_error_detail_message():
    """The 400 error detail must mention uuid4 to aid debugging."""
    with pytest.raises(HTTPException) as exc_info:
        _validate_job_id("not-valid")
    assert "uuid4" in exc_info.value.detail.lower()


def test_validate_job_id_rejects_uuid_with_extra_characters():
    """A UUID4 with extra leading/trailing characters must be rejected (anchored regex)."""
    valid = str(uuid.uuid4())
    with pytest.raises(HTTPException):
        _validate_job_id(f" {valid}")  # leading space
    with pytest.raises(HTTPException):
        _validate_job_id(f"{valid} ")  # trailing space
    with pytest.raises(HTTPException):
        _validate_job_id(f"x{valid}")  # prefix


def test_validate_job_id_rejects_uuid_without_hyphens():
    """A UUID4 without hyphens (hex-only) must be rejected — not the canonical format."""
    # uuid.uuid4().hex returns 32 hex chars, no hyphens
    no_hyphens = uuid.uuid4().hex
    with pytest.raises(HTTPException) as exc_info:
        _validate_job_id(no_hyphens)
    assert exc_info.value.status_code == 400


# ── HTTP endpoint tests for /v1/jobs/{job_id} ─────────────────────────────────

@pytest.fixture
def auth_client(monkeypatch):
    """TestClient with auth enforced and a known token."""
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "0")
    monkeypatch.setenv("ORAMA_CONTROL_PLANE_TOKEN", "test-job-token")
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-job-token"}


def test_get_job_invalid_id_returns_400(auth_client, auth_headers):
    """GET /v1/jobs/<invalid> must return 400 before any supervisor lookup."""
    resp = auth_client.get("/v1/jobs/../etc/passwd", headers=auth_headers)
    # FastAPI may route this differently; test with a clearly invalid segment
    resp2 = auth_client.get("/v1/jobs/not-a-uuid", headers=auth_headers)
    assert resp2.status_code == 400


def test_get_job_path_traversal_returns_4xx(auth_client, auth_headers):
    """GET /v1/jobs/<path-traversal-string> must be rejected (400 or 404).

    When %2F-encoded slashes are present, Starlette normalises the path before
    routing and the route may not match (404). Both 400 (UUID validation) and
    404 (no route match) are valid rejections — neither allows 2xx for traversal.
    """
    import urllib.parse
    traversal = urllib.parse.quote("../../etc/passwd", safe="")
    resp = auth_client.get(f"/v1/jobs/{traversal}", headers=auth_headers)
    assert resp.status_code in (400, 404), (
        f"path traversal must not succeed; got {resp.status_code}"
    )


def test_get_job_valid_uuid4_not_found_returns_404_with_new_message(auth_client, auth_headers):
    """GET /v1/jobs/<valid-uuid4> for non-existent job must return 404.

    Error detail must be the new 'Job not found' message (not the old
    'Job <id> not found' which leaked the job_id back to the caller).
    """
    valid_id = str(uuid.uuid4())
    resp = auth_client.get(f"/v1/jobs/{valid_id}", headers=auth_headers)
    assert resp.status_code == 404
    body = resp.json()
    assert body.get("detail") == "Job not found", (
        f"Expected 'Job not found' but got: {body.get('detail')!r}"
    )


def test_get_job_404_detail_does_not_leak_job_id(auth_client, auth_headers):
    """The 404 error message must not echo back the job_id (information leak prevention)."""
    valid_id = str(uuid.uuid4())
    resp = auth_client.get(f"/v1/jobs/{valid_id}", headers=auth_headers)
    assert resp.status_code == 404
    detail = resp.json().get("detail", "")
    assert valid_id not in detail, (
        f"404 response must not echo the job_id; got: {detail!r}"
    )


def test_cancel_job_invalid_id_returns_400(auth_client, auth_headers):
    """POST /v1/jobs/<invalid>/cancel must return 400."""
    resp = auth_client.post("/v1/jobs/not-a-uuid/cancel", headers=auth_headers)
    assert resp.status_code == 400


def test_cancel_job_path_traversal_returns_4xx(auth_client, auth_headers):
    """POST /v1/jobs/<traversal>/cancel must be rejected (400 or 404).

    Starlette normalises %2F-encoded slashes in the path before routing,
    so the handler may never be reached (404). Both 400 and 404 are valid
    rejections — neither allows 2xx for a path traversal attempt.
    """
    import urllib.parse
    traversal = urllib.parse.quote("../jobs/other", safe="")
    resp = auth_client.post(f"/v1/jobs/{traversal}/cancel", headers=auth_headers)
    assert resp.status_code in (400, 404), (
        f"path traversal must not succeed; got {resp.status_code}"
    )


def test_cancel_job_valid_uuid4_unknown_returns_cancel_requested_false(auth_client, auth_headers):
    """POST /v1/jobs/<valid-uuid4>/cancel for unknown job returns 200 with cancel_requested=False."""
    valid_id = str(uuid.uuid4())
    resp = auth_client.post(f"/v1/jobs/{valid_id}/cancel", headers=auth_headers)
    # cancel() returns False for unknown jobs; endpoint returns 200 regardless
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("job_id") == valid_id
    assert body.get("cancel_requested") is False


def test_replay_job_invalid_id_returns_400(auth_client, auth_headers):
    """POST /v1/jobs/<invalid>/replay must return 400."""
    resp = auth_client.post("/v1/jobs/not-a-uuid/replay", headers=auth_headers)
    assert resp.status_code == 400


def test_replay_job_path_traversal_returns_4xx(auth_client, auth_headers):
    """POST /v1/jobs/<path-traversal>/replay must be rejected (400 or 404).

    Starlette normalises %2F-encoded slashes in the path before routing,
    so the handler may never be reached (404). Both 400 and 404 are valid
    rejections — neither allows 2xx for a path traversal attempt.
    """
    import urllib.parse
    traversal = urllib.parse.quote("../../state/jobs/other", safe="")
    resp = auth_client.post(f"/v1/jobs/{traversal}/replay", headers=auth_headers)
    assert resp.status_code in (400, 404), (
        f"path traversal must not succeed; got {resp.status_code}"
    )


def test_replay_job_valid_uuid4_not_found_returns_404_with_new_message(auth_client, auth_headers):
    """POST /v1/jobs/<valid-uuid4>/replay for unknown job must return 404 'Job not found'.

    The old behaviour raised HTTPException(detail=str(exc)) which could leak
    internal error strings. The new behaviour normalises to 'Job not found'.
    """
    valid_id = str(uuid.uuid4())
    resp = auth_client.post(f"/v1/jobs/{valid_id}/replay", headers=auth_headers)
    assert resp.status_code == 404
    body = resp.json()
    assert body.get("detail") == "Job not found", (
        f"Expected 'Job not found' but got: {body.get('detail')!r}"
    )


def test_replay_404_detail_does_not_leak_exception_message(auth_client, auth_headers):
    """The 404 on replay must not forward the internal ValueError message.

    Previously: detail=str(exc) which could expose internal state.
    Now: fixed string 'Job not found'.
    """
    valid_id = str(uuid.uuid4())
    resp = auth_client.post(f"/v1/jobs/{valid_id}/replay", headers=auth_headers)
    assert resp.status_code == 404
    detail = resp.json().get("detail", "")
    # Must not contain exception boilerplate
    assert "not found" in detail.lower()
    assert "ValueError" not in detail
    assert valid_id not in detail


def test_job_endpoints_require_auth_by_default(monkeypatch):
    """All /v1/jobs/{job_id} endpoints must enforce auth in the default (secure) config."""
    monkeypatch.delenv("ORAMA_INSECURE_DEV", raising=False)
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)

    valid_id = str(uuid.uuid4())
    with TestClient(app, raise_server_exceptions=False) as client:
        get_resp = client.get(f"/v1/jobs/{valid_id}")
        cancel_resp = client.post(f"/v1/jobs/{valid_id}/cancel")
        replay_resp = client.post(f"/v1/jobs/{valid_id}/replay")

    assert get_resp.status_code == 401
    assert cancel_resp.status_code == 401
    assert replay_resp.status_code == 401


def test_validate_job_id_400_detail_is_client_safe():
    """The 400 detail must be a plain string suitable for returning to clients."""
    with pytest.raises(HTTPException) as exc_info:
        _validate_job_id("../../../etc/shadow")
    assert isinstance(exc_info.value.detail, str)
    # Must not echo back the malicious input in a way that enables reflected injection
    # (the detail is a fixed string, not user input)
    assert exc_info.value.detail == "job_id must be a uuid4-formatted server-issued identifier"
