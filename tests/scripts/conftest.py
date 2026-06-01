"""Local conftest for scripts/ shell-script tests.

Overrides the autouse ``_orama_insecure_dev_for_tests`` fixture from the parent
conftest.py so that these tests do not require fastapi or the orchestrator package.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _orama_insecure_dev_for_tests(monkeypatch):  # noqa: PT004
    """
    Provide an autouse pytest fixture that enables insecure dev mode and clears the control plane token for shell-script tests.
    
    This no-op override sets the ORAMA_INSECURE_DEV environment variable to "1" and removes ORAMA_CONTROL_PLANE_TOKEN (if present) so the tests can run without requiring the orchestrator or FastAPI fixtures.
    
    Parameters:
        monkeypatch: pytest.MonkeyPatch fixture used to modify environment variables for the test.
    """
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "1")
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)