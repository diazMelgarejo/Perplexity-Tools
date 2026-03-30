"""conftest.py — session-scoped test fixtures for Perplexity-Tools.

Cleans ephemeral state files that are written by the real AgentTracker and
CostGuard during test runs. Without this, stale "idle" agents from a previous
session cause /orchestrate to return {"status": "conflict"} on the very first
call in a new session, breaking any test that expects {"status": "created"}.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_STATE_DIR = Path(__file__).parent.parent / ".state"
_AGENTS_FILE = _STATE_DIR / "agents.json"


@pytest.fixture(autouse=True, scope="session")
def clean_agent_state():
    """Delete stale agent registry before and after each test session."""
    _AGENTS_FILE.unlink(missing_ok=True)
    yield
    _AGENTS_FILE.unlink(missing_ok=True)
