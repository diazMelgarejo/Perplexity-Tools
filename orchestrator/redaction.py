"""Central redaction for configs, logs, memory payloads, and operator surfaces."""
from __future__ import annotations

import re
from typing import Any, Mapping, MutableMapping

# High-confidence secret patterns — shared across memory, logs, and config reads.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_-]{20,}")),
    ("telegram_bot_token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b")),
    ("github_pat", re.compile(r"\bghp_[0-9A-Za-z]{20,}\b")),
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("anthropic_api_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}\b", re.IGNORECASE)),
)
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_REDACTED = "[REDACTED]"

# Credential / config keys — replace entirely (never index or echo).
_CREDENTIAL_KEYS = frozenset(
    {
        "api_key",
        "apiKey",
        "token",
        "secret",
        "password",
        "authorization",
        "botToken",
        "paths",
        "path",
        "backend_urls",
        "backend_url",
        "openclaw_config",
        "metadata",
    }
)

# Prompt-like content — strip secret patterns in place so FTS5 recall still works.
_CONTENT_KEYS = frozenset(
    {
        "raw_prompt",
        "prompt",
        "transcript",
        "messages",
        "tool_trace",
        "tool_traces",
        "chain_of_thought",
        "model_internals",
    }
)

_SENSITIVE_KEYS = _CREDENTIAL_KEYS | _CONTENT_KEYS


def redact_text(value: str) -> str:
    """Redact secrets and emails from a string."""
    if not value:
        return value
    redacted = value
    for _, pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(_REDACTED, redacted)
    redacted = _EMAIL_PATTERN.sub(_REDACTED, redacted)
    return redacted


def redact_value(value: Any) -> Any:
    """Recursively redact mapping/list/string values."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return redact_mapping(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


def redact_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Redact credentials and secret patterns; keep searchable prompt text when safe."""
    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        if key in _CREDENTIAL_KEYS:
            redacted[key] = _REDACTED
            continue
        if key in _CONTENT_KEYS:
            redacted[key] = redact_value(value)
            continue
        redacted[key] = redact_value(value)
    return redacted


def contains_secret(value: str) -> bool:
    """Return True when text matches a high-confidence secret pattern."""
    if not value:
        return False
    if any(pattern.search(value) for _, pattern in _SECRET_PATTERNS):
        return True
    return False


def redact_for_logs(payload: MutableMapping[str, Any]) -> dict[str, Any]:
    """Operator-safe view for log tail and debug surfaces."""
    return redact_mapping(payload)
