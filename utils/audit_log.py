"""utils/audit_log.py — Append-only, immutable audit event log.

Provides a thread-safe, file-backed append-only log for OrchestrationSession
audit events. Each event is a newline-delimited JSON record (NDJSON).

Design rules:
- Append-only: no delete, no overwrite, no truncate.
- Immutable entries: records are written once, never modified.
- File-backed: persists across process restarts.
- Thread-safe: uses a per-path lock for concurrent appenders.
- NDJSON: one JSON object per line, terminated by newline.

Usage:
    from utils.audit_log import AuditLog, append_event
    from orchestrator.contracts import AuditEvent
    from datetime import datetime, timezone

    log = AuditLog(".state/sessions/abc/audit.ndjson")
    log.append(AuditEvent(ts=datetime.now(timezone.utc), event="worker.dispatched",
                          actor="orch-1", detail={"job_id": "j1"}))

    # Or module-level convenience:
    append_event(".state/sessions/abc/audit.ndjson",
                 event="verifier.approved", actor="verifier-j2")
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# ── Thread-safety: one lock per resolved path ──────────────────────────────────
_LOCKS: Dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: str) -> threading.Lock:
    with _LOCKS_GUARD:
        if path not in _LOCKS:
            _LOCKS[path] = threading.Lock()
        return _LOCKS[path]


# ── AuditLog class ─────────────────────────────────────────────────────────────

class AuditLog:
    """Append-only NDJSON event log for a single session.

    Creates parent directories on first write. Never truncates or deletes.
    """

    def __init__(self, path: str) -> None:
        self._path = Path(path).resolve()
        self._path_str = str(self._path)

    # ── Public API ─────────────────────────────────────────────────────────────

    def append(self, event: "AuditEvent") -> None:  # noqa: F821
        """Append one AuditEvent to the log. Thread-safe."""
        record = {
            "ts": event.ts.isoformat(),
            "event": event.event,
            "actor": event.actor,
            "detail": event.detail,
        }
        self._write_record(record)

    def append_raw(
        self,
        *,
        event: str,
        actor: str,
        detail: Optional[Dict[str, Any]] = None,
        ts: Optional[datetime] = None,
    ) -> None:
        """Append a raw event without constructing an AuditEvent model.

        Useful in contexts where contracts.py is not yet importable.
        """
        record = {
            "ts": (ts or datetime.now(timezone.utc)).isoformat(),
            "event": event,
            "actor": actor,
            "detail": detail or {},
        }
        self._write_record(record)

    def read_all(self) -> list:
        """Return all records as a list of dicts. Returns [] if file missing."""
        lock = _lock_for(self._path_str)
        with lock:
            if not self._path.exists():
                return []
            try:
                with open(self._path_str, "r", encoding="utf-8") as fh:
                    lines = fh.read().splitlines()
                return [json.loads(line) for line in lines if line.strip()]
            except (OSError, json.JSONDecodeError):
                return []

    def count(self) -> int:
        """Return the number of records currently in the log."""
        return len(self.read_all())

    # ── Internal ───────────────────────────────────────────────────────────────

    def _write_record(self, record: Dict[str, Any]) -> None:
        lock = _lock_for(self._path_str)
        with lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # plain open() avoids pathlib EDEADLK on macOS launchd (see commit a82ab51)
            with open(self._path_str, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, separators=(",", ":")) + "\n")
                fh.flush()


# ── Module-level convenience ───────────────────────────────────────────────────

def append_event(
    log_path: str,
    *,
    event: str,
    actor: str,
    detail: Optional[Dict[str, Any]] = None,
    ts: Optional[datetime] = None,
) -> None:
    """Append a single event to the given NDJSON log file.

    Creates parent directories as needed. Thread-safe. Never raises on I/O
    errors — logs a warning instead (audit log must not crash worker paths).
    """
    import logging as _logging
    try:
        AuditLog(log_path).append_raw(event=event, actor=actor, detail=detail, ts=ts)
    except Exception as exc:  # noqa: BLE001
        _logging.warning("audit_log.append_event failed for %s: %s", log_path, exc)
