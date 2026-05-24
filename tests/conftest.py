"""Pytest defaults for Perpetua-Tools."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _orama_insecure_dev_for_tests(monkeypatch):
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "1")
    monkeypatch.delenv("ORAMA_CONTROL_PLANE_TOKEN", raising=False)
