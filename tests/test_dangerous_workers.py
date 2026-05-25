"""Tests for PT_ALLOW_DANGEROUS_CLI_WORKERS gate (security fix 6)."""
from __future__ import annotations

import os

import pytest

from orchestrator.dangerous_workers import (
    DANGEROUS_CLI_BACKENDS,
    assert_dangerous_cli_worker_allowed,
    dangerous_cli_workers_enabled,
)


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_dangerous_cli_enabled_truthy(monkeypatch, value: str) -> None:
    monkeypatch.setenv("PT_ALLOW_DANGEROUS_CLI_WORKERS", value)
    assert dangerous_cli_workers_enabled() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no"])
def test_dangerous_cli_disabled(monkeypatch, value: str) -> None:
    if value:
        monkeypatch.setenv("PT_ALLOW_DANGEROUS_CLI_WORKERS", value)
    else:
        monkeypatch.delenv("PT_ALLOW_DANGEROUS_CLI_WORKERS", raising=False)
    assert dangerous_cli_workers_enabled() is False


def test_assert_blocks_codex_by_default(monkeypatch) -> None:
    monkeypatch.delenv("PT_ALLOW_DANGEROUS_CLI_WORKERS", raising=False)
    with pytest.raises(RuntimeError, match="PT_ALLOW_DANGEROUS_CLI_WORKERS"):
        assert_dangerous_cli_worker_allowed("codex")


def test_assert_allows_ollama_without_flag(monkeypatch) -> None:
    monkeypatch.delenv("PT_ALLOW_DANGEROUS_CLI_WORKERS", raising=False)
    assert_dangerous_cli_worker_allowed("ollama")


def test_all_dangerous_backends_gated(monkeypatch) -> None:
    monkeypatch.delenv("PT_ALLOW_DANGEROUS_CLI_WORKERS", raising=False)
    for backend in DANGEROUS_CLI_BACKENDS:
        with pytest.raises(RuntimeError):
            assert_dangerous_cli_worker_allowed(backend)


def test_all_dangerous_backends_allowed_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("PT_ALLOW_DANGEROUS_CLI_WORKERS", "1")
    for backend in DANGEROUS_CLI_BACKENDS:
        assert_dangerous_cli_worker_allowed(backend)
