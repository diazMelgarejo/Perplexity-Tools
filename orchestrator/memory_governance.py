"""Memory governance — classify and redact payloads before durable store."""
from __future__ import annotations

from typing import Any, Literal

from orchestrator.redaction import contains_secret, redact_mapping

MemoryClass = Literal["operational", "prompt", "error", "routing", "heartbeat"]

_PROMPT_EVENT_TYPES = frozenset({"dispatch", "result"})
_ERROR_EVENT_TYPES = frozenset({"error"})
_ROUTING_EVENT_TYPES = frozenset({"route"})


def classify_event(event_type: str, payload: dict[str, Any]) -> MemoryClass:
    if event_type in _ERROR_EVENT_TYPES:
        return "error"
    if event_type in _ROUTING_EVENT_TYPES:
        return "routing"
    if event_type in _PROMPT_EVENT_TYPES or "prompt" in payload or "messages" in payload:
        return "prompt"
    if event_type == "heartbeat":
        return "heartbeat"
    return "operational"


def classify_and_redact(
    payload: dict[str, Any],
    *,
    event_type: str = "",
) -> tuple[dict[str, Any], MemoryClass]:
    """Return redacted payload safe for SQLite FTS and LanceDB embedding."""
    memory_class = classify_event(event_type, payload)
    redacted = redact_mapping(dict(payload))
    redacted["_memory_class"] = memory_class
    if contains_secret(str(payload)):
        redacted["_redaction_applied"] = True
    return redacted, memory_class
