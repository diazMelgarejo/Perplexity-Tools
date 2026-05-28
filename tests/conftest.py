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
def _orama_insecure_dev_for_tests(monkeypatch, tmp_path):
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "1")
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)
    # Redirect the persisted-token path to a fresh tmp dir so that
    # ensure_control_plane_token() cannot read a token written by a previous
    # test and load it back into os.environ — which would make auth_enforced()
    # return True and cause spurious 401s even when ORAMA_INSECURE_DEV=1.
    monkeypatch.setattr(
        "orchestrator.control_plane_auth.DEFAULT_TOKEN_PATH",
        tmp_path / "control_plane_token",
    )
    # Defensive: clear LAN discovery env vars that could leak across tests.
    # test_detect_active_tilting_ip_lm_studio_win_endpoints_without_http sets
    # LM_STUDIO_WIN_ENDPOINTS="192.168.254.108" (no port) via monkeypatch. If
    # monkeypatch teardown misses the restore in some Python/platform combos,
    # detect_active_tilting_ip() picks up the leaked value and returns it before
    # reaching the socket-detection branch, causing CI socket-mock tests to fail.
    monkeypatch.delenv("LM_STUDIO_WIN_ENDPOINTS", raising=False)
    monkeypatch.delenv("LAN_GPU_IP_OVERRIDE", raising=False)
