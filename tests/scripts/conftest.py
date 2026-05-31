"""Local conftest for scripts/ shell-script tests.

Overrides the autouse ``_orama_insecure_dev_for_tests`` fixture from the parent
conftest.py so that these tests do not require fastapi or the orchestrator package.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _orama_insecure_dev_for_tests(monkeypatch):  # noqa: PT004
    """No-op override — shell-script tests don't need orchestrator fixtures."""
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "1")
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)