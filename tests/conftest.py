"""conftest.py — session-scoped test fixtures for Perpetua-Tools.

Cleans ephemeral state files that are written by the real AgentTracker and
CostGuard during test runs. Without this, stale "idle" agents from a previous
session cause /orchestrate to return {"status": "conflict"} on the very first
call in a new session, breaking any test that expects {"status": "created"}.

Also disables ECC Tools live git sync so tests never hit the network.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the Perpetua-Tools repo root is on sys.path regardless of pytest CWD
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import os
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


@pytest.fixture(autouse=True, scope="session")
def disable_ecc_sync_for_tests():
    """Prevent live git clone/pull during the test session (offline / CI safety)."""
    prev = os.environ.get("ECC_SYNC_ENABLED")
    os.environ["ECC_SYNC_ENABLED"] = "false"
    yield
    if prev is None:
        os.environ.pop("ECC_SYNC_ENABLED", None)
    else:
        os.environ["ECC_SYNC_ENABLED"] = prev
