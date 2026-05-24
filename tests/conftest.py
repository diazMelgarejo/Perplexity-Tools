"""Pytest defaults for Perpetua-Tools.

Cleans ephemeral agent state and disables live ECC sync during test sessions.
Also opts tests out of control-plane bearer auth unless a test overrides env.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_STATE_DIR = _REPO_ROOT / ".state"
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


@pytest.fixture(autouse=True)
def _orama_insecure_dev_for_tests(monkeypatch):
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "1")
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)
