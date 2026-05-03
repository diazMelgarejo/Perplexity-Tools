"""
orchestrator/onboarding.py — Perpetua-Tools
----------------------------------------------
Manages .state/onboarding.json — lightweight forward-compat state bridge
for portal v1.1 and the start.sh security warning.

Schema (all fields optional / additive):
{
  "alphaclaw": {
    "password_is_default": true | false,   # true → show security warning
    "gateway_url":  "http://127.0.0.1:18789",
    "gateway_ready": true | false,
    "install_dir": "/home/user/.alphaclaw",
    "key_configured": true | false,        # GITHUB_TOKEN present
    "windows_detected": true | false       # WIN_IP resolved via NetworkAutoConfig
  }
}
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# Resolve state file relative to PT_HOME so it works regardless of cwd.
_PT_HOME = Path(os.getenv("PT_HOME", str(Path(__file__).resolve().parent.parent)))
_STATE_FILE = _PT_HOME / ".state" / "onboarding.json"


def _state_path() -> Path:
    """Return the resolved path (re-evaluated each call to honour env changes)."""
    pt_home = Path(os.getenv("PT_HOME", str(Path(__file__).resolve().parent.parent)))
    return pt_home / ".state" / "onboarding.json"


def read_onboarding_state() -> dict:
    """Load .state/onboarding.json; return {} on missing or parse error."""
    path = _state_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def write_onboarding_state(updates: dict) -> None:
    """Deep-merge *updates* into existing state and persist."""
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    state = read_onboarding_state()
    # Deep-merge one level (dict values are merged, not replaced)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(state.get(key), dict):
            state[key] = {**state[key], **value}
        else:
            state[key] = value
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def is_secure() -> bool:
    """Return True if AlphaClaw is NOT using the default password.

    Defaults to True (optimistic) when no state file exists so that we
    only warn when we *know* the default is in use.
    """
    state = read_onboarding_state()
    alphaclaw = state.get("alphaclaw", {})
    # password_is_default missing → we don't know → optimistic (no warning)
    return not alphaclaw.get("password_is_default", False)
