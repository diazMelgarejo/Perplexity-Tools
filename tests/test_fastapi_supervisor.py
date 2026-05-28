"""tests/test_fastapi_supervisor.py — Tests for V1 supervisor HTTP endpoints.

Covers the changes introduced in the 2026-05-28 security audit:
  - _validate_job_id(): UUID4 format enforcement at the HTTP boundary
  - 404 detail text sanitisation ("Job not found" — no job_id echo)
  - _UUID4_RE regex behaviour (valid / invalid patterns)

All tests run with ORAMA_INSECURE_DEV=1 (conftest.py autouse) so auth is
disabled and the tests focus exclusively on the job-id validation layer.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from orchestrator.fastapi_app import _UUID4_RE, _validate_job_id, app


# ── _validate_job_id unit tests ───────────────────────────────────────────────


class TestValidateJobIdUnit:
    """Direct unit tests for _validate_job_id()."""

    # --- valid inputs ---

    def test_valid_uuid4_lowercase_passes(self):
        jid = "550e8400-e29b-41d4-a716-446655440000"
        # version nibble is '4', variant nibble is 'a'
        valid = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
        result = _validate_job_id(valid)
        assert result == valid

    def test_valid_uuid4_uppercase_passes(self):
        """_UUID4_RE is IGNORECASE — uppercase letters must be accepted."""
        jid = "3FA85F64-5717-4562-B3FC-2C963F66AFA6"
        result = _validate_job_id(jid)
        assert result == jid

    def test_valid_uuid4_mixed_case_passes(self):
        jid = "3Fa85F64-5717-4562-b3fc-2C963f66AfA6"
        result = _validate_job_id(jid)
        assert result == jid

    def test_valid_uuid4_variant_8_passes(self):
        """Variant nibble '8' is valid (RFC 4122 variant bits 10xx)."""
        jid = "550e8400-e29b-4abc-8def-446655440000"
        result = _validate_job_id(jid)
        assert result == jid

    def test_valid_uuid4_variant_9_passes(self):
        jid = "550e8400-e29b-4abc-9def-446655440000"
        result = _validate_job_id(jid)
        assert result == jid

    def test_valid_uuid4_variant_a_passes(self):
        jid = "550e8400-e29b-4abc-adef-446655440000"
        result = _validate_job_id(jid)
        assert result == jid

    def test_valid_uuid4_variant_b_passes(self):
        jid = "550e8400-e29b-4abc-bdef-446655440000"
        result = _validate_job_id(jid)
        assert result == jid

    # --- invalid inputs → HTTP 400 ---

    def test_empty_string_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_job_id("")
        assert exc_info.value.status_code == 400

    def test_plain_string_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_job_id("not-a-uuid")
        assert exc_info.value.status_code == 400

    def test_uuid1_version_rejected(self):
        """UUID v1 has version nibble '1', not '4'."""
        uuid1 = "550e8400-e29b-11d4-a716-446655440000"
        with pytest.raises(HTTPException) as exc_info:
            _validate_job_id(uuid1)
        assert exc_info.value.status_code == 400

    def test_uuid3_version_rejected(self):
        """UUID v3 has version nibble '3', not '4'."""
        uuid3 = "550e8400-e29b-31d4-a716-446655440000"
        with pytest.raises(HTTPException) as exc_info:
            _validate_job_id(uuid3)
        assert exc_info.value.status_code == 400

    def test_uuid5_version_rejected(self):
        """UUID v5 has version nibble '5', not '4'."""
        uuid5 = "550e8400-e29b-51d4-a716-446655440000"
        with pytest.raises(HTTPException) as exc_info:
            _validate_job_id(uuid5)
        assert exc_info.value.status_code == 400

    def test_invalid_variant_nibble_rejected(self):
        """Variant nibbles outside [89ab] are rejected."""
        bad_variant = "550e8400-e29b-41d4-c716-446655440000"  # 'c' is not valid
        with pytest.raises(HTTPException) as exc_info:
            _validate_job_id(bad_variant)
        assert exc_info.value.status_code == 400

    def test_path_traversal_double_dot_rejected(self):
        """'..'-style path traversal must be rejected."""
        with pytest.raises(HTTPException) as exc_info:
            _validate_job_id("../../etc/passwd")
        assert exc_info.value.status_code == 400

    def test_path_traversal_absolute_path_rejected(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_job_id("/etc/shadow")
        assert exc_info.value.status_code == 400

    def test_path_traversal_with_null_byte_rejected(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_job_id("3fa85f64-5717-4562-b3fc-2c963f66afa6\x00../evil")
        assert exc_info.value.status_code == 400

    def test_uuid_with_no_hyphens_rejected(self):
        """Bare hex without hyphens must be rejected."""
        with pytest.raises(HTTPException) as exc_info:
            _validate_job_id("3fa85f6457174562b3fc2c963f66afa6")
        assert exc_info.value.status_code == 400

    def test_uuid_too_short_rejected(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_job_id("3fa85f64-5717-4562-b3fc")
        assert exc_info.value.status_code == 400

    def test_uuid_too_long_rejected(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_job_id("3fa85f64-5717-4562-b3fc-2c963f66afa6-extra")
        assert exc_info.value.status_code == 400

    def test_uuid_with_leading_space_rejected(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_job_id(" 3fa85f64-5717-4562-b3fc-2c963f66afa6")
        assert exc_info.value.status_code == 400

    def test_error_detail_message(self):
        """The 400 detail must contain 'uuid4' to guide callers."""
        with pytest.raises(HTTPException) as exc_info:
            _validate_job_id("bad-id")
        assert "uuid4" in exc_info.value.detail.lower()

    def test_returns_original_job_id_unchanged(self):
        """_validate_job_id must return the original string unmodified."""
        jid = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
        assert _validate_job_id(jid) is jid


# ── _UUID4_RE regex unit tests ────────────────────────────────────────────────


class TestUUID4Regex:
    """Low-level regex correctness tests."""

    def test_matches_canonical_uuid4(self):
        assert _UUID4_RE.match("3fa85f64-5717-4562-b3fc-2c963f66afa6")

    def test_does_not_match_partial(self):
        assert not _UUID4_RE.match("3fa85f64-5717-4562-b3fc")

    def test_does_not_match_version_1(self):
        assert not _UUID4_RE.match("3fa85f64-5717-1562-b3fc-2c963f66afa6")

    def test_does_not_match_invalid_variant(self):
        assert not _UUID4_RE.match("3fa85f64-5717-4562-d3fc-2c963f66afa6")

    def test_matches_all_valid_variants(self):
        for v in ("8", "9", "a", "b", "A", "B"):
            jid = f"3fa85f64-5717-4562-{v}3fc-2c963f66afa6"
            assert _UUID4_RE.match(jid), f"Expected match for variant nibble {v!r}"

    def test_does_not_match_non_hex_chars(self):
        assert not _UUID4_RE.match("zfa85f64-5717-4562-b3fc-2c963f66afa6")


# ── HTTP endpoint integration tests ───────────────────────────────────────────
# conftest.py sets ORAMA_INSECURE_DEV=1 (autouse) so auth is bypassed here.


class TestGetJobEndpointValidation:
    """GET /v1/jobs/{job_id} — invalid job_id format → 400 before any DB lookup."""

    def test_invalid_job_id_returns_400(self):
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/v1/jobs/not-a-uuid")
        assert resp.status_code == 400

    def test_path_traversal_returns_400(self):
        # Starlette normalises `../` segments before routing, so traversal
        # URLs like `/v1/jobs/../../etc/passwd` become `/etc/passwd` and reach
        # no registered route → 404.  Either status proves the traversal is
        # rejected without returning job data.
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/v1/jobs/../../etc/passwd")
        assert resp.status_code in (400, 404), (
            f"path traversal must not succeed; got {resp.status_code}"
        )

    def test_valid_unknown_uuid4_returns_404(self):
        """Valid UUID4 format but no matching job → 404 (not 400)."""
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/v1/jobs/3fa85f64-5717-4562-b3fc-2c963f66afa6")
        assert resp.status_code == 404

    def test_404_detail_does_not_echo_job_id(self):
        """The 404 detail must be the sanitised 'Job not found', not f'Job {id} not found'."""
        jid = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/v1/jobs/{jid}")
        assert resp.status_code == 404
        detail = resp.json().get("detail", "")
        assert jid not in detail, "job_id must not be echoed in the 404 detail"
        assert detail == "Job not found"

    def test_uuid1_returns_400_not_404(self):
        """UUID v1 must be rejected at validation, not looked up."""
        uuid1 = "550e8400-e29b-11d4-a716-446655440000"
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(f"/v1/jobs/{uuid1}")
        assert resp.status_code == 400


class TestCancelJobEndpointValidation:
    """POST /v1/jobs/{job_id}/cancel — invalid job_id → 400."""

    def test_invalid_job_id_returns_400(self):
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/v1/jobs/malicious-id/cancel")
        assert resp.status_code == 400

    def test_path_traversal_returns_400(self):
        # Starlette normalises `../` before routing; `/v1/jobs/../admin/cancel`
        # becomes `/admin/cancel` → no route → 404.  Both 400 and 404 confirm
        # the traversal is blocked.
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/v1/jobs/../admin/cancel")
        assert resp.status_code in (400, 404), (
            f"path traversal must not succeed; got {resp.status_code}"
        )

    def test_valid_uuid4_returns_200_cancel_false(self):
        """Valid UUID4 for a non-existent job → 200 with cancel_requested=False."""
        jid = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(f"/v1/jobs/{jid}/cancel")
        assert resp.status_code == 200
        body = resp.json()
        assert body["job_id"] == jid
        assert body["cancel_requested"] is False

    def test_400_detail_contains_uuid4(self):
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/v1/jobs/bad-id/cancel")
        assert "uuid4" in resp.json().get("detail", "").lower()


class TestReplayJobEndpointValidation:
    """POST /v1/jobs/{job_id}/replay — invalid job_id → 400, unknown valid → 404."""

    def test_invalid_job_id_returns_400(self):
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/v1/jobs/bad-format/replay")
        assert resp.status_code == 400

    def test_path_traversal_returns_400(self):
        # Starlette normalises `../` before routing; `/v1/jobs/../../secret/replay`
        # becomes `/secret/replay` → no route → 404.  Both 400 and 404 confirm
        # the traversal is blocked without returning job data.
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/v1/jobs/../../secret/replay")
        assert resp.status_code in (400, 404), (
            f"path traversal must not succeed; got {resp.status_code}"
        )

    def test_valid_unknown_uuid4_returns_404(self):
        """Valid UUID4 format but no matching job → 404."""
        jid = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(f"/v1/jobs/{jid}/replay")
        assert resp.status_code == 404

    def test_404_detail_is_sanitised(self):
        """The 404 must say 'Job not found', not expose the job_id."""
        jid = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(f"/v1/jobs/{jid}/replay")
        assert resp.status_code == 404
        detail = resp.json().get("detail", "")
        assert jid not in detail
        assert detail == "Job not found"

    def test_400_detail_contains_uuid4(self):
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/v1/jobs/not-a-uuid/replay")
        assert "uuid4" in resp.json().get("detail", "").lower()