"""Policy tests for utils.model_endpoint_url (Security Fix 5)."""
from __future__ import annotations

import pytest

from utils.model_endpoint_url import (
    ModelEndpointPolicyError,
    allow_public_model_endpoints,
    parse_model_endpoint_list,
    redact_endpoint_for_log,
    validate_model_endpoint_url,
)


@pytest.fixture(autouse=True)
def _clear_public_opt_in(monkeypatch):
    monkeypatch.delenv("ALLOW_PUBLIC_MODEL_ENDPOINTS", raising=False)


class TestLoopbackAndPrivate:
    def test_localhost_allowed(self):
        assert validate_model_endpoint_url("http://localhost:1234") == "http://localhost:1234"

    def test_127_allowed(self):
        assert validate_model_endpoint_url("http://127.0.0.1:11434") == "http://127.0.0.1:11434"

    def test_rfc1918_192_allowed(self):
        url = validate_model_endpoint_url("http://192.168.254.102:1234")
        assert url == "http://192.168.254.102:1234"

    def test_rfc1918_10_allowed(self):
        assert validate_model_endpoint_url("http://10.0.0.5:1234") == "http://10.0.0.5:1234"

    def test_rfc1918_172_allowed(self):
        assert validate_model_endpoint_url("http://172.16.1.2:1234") == "http://172.16.1.2:1234"

    def test_parse_comma_list(self):
        raw = "http://192.168.1.1:1234, http://127.0.0.1:1234"
        assert parse_model_endpoint_list(raw) == [
            "http://192.168.1.1:1234",
            "http://127.0.0.1:1234",
        ]


class TestPublicBlocked:
    def test_public_ip_blocked(self):
        with pytest.raises(ModelEndpointPolicyError, match="RFC1918"):
            validate_model_endpoint_url("http://8.8.8.8:1234")

    def test_public_hostname_blocked(self):
        with pytest.raises(ModelEndpointPolicyError):
            validate_model_endpoint_url("http://evil.example.com:1234")

    def test_public_ip_allowed_with_opt_in(self, monkeypatch):
        monkeypatch.setenv("ALLOW_PUBLIC_MODEL_ENDPOINTS", "1")
        assert allow_public_model_endpoints()
        assert validate_model_endpoint_url("http://8.8.8.8:1234") == "http://8.8.8.8:1234"

    def test_public_hostname_allowed_with_opt_in(self, monkeypatch):
        monkeypatch.setenv("ALLOW_PUBLIC_MODEL_ENDPOINTS", "true")
        assert validate_model_endpoint_url("http://lm.example.com:1234") == (
            "http://lm.example.com:1234"
        )


class TestMalformed:
    def test_file_scheme_rejected(self):
        with pytest.raises(ModelEndpointPolicyError, match="scheme"):
            validate_model_endpoint_url("file:///etc/passwd")

    def test_credentials_rejected(self):
        with pytest.raises(ModelEndpointPolicyError, match="credentials"):
            validate_model_endpoint_url("http://user:pass@192.168.1.1:1234")

    def test_empty_rejected(self):
        with pytest.raises(ModelEndpointPolicyError, match="empty"):
            validate_model_endpoint_url("   ")


class TestLoggingRedaction:
    def test_private_ip_redacted(self):
        out = redact_endpoint_for_log("http://192.168.254.102:1234")
        assert "254.102" not in out
        assert "192.168.254.*" in out

    def test_localhost_not_redacted(self):
        assert "localhost" in redact_endpoint_for_log("http://localhost:1234")
