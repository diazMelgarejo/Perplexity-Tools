"""Tests for explicit dispatch model resolution (anti-mirror policy)."""

from __future__ import annotations

import pytest

from utils.dispatch_models import (
    backend_never_empty_model,
    ensure_metadata_model,
    mac_lmstudio_default_model,
    resolve_dispatch_model,
)


def test_lmstudio_mac_never_empty_model_flag():
    assert backend_never_empty_model("lmstudio-mac") is True
    assert backend_never_empty_model("ollama") is False


def test_lmstudio_mac_empty_metadata_uses_mac_default():
    model = resolve_dispatch_model("lmstudio-mac", {})
    assert model == mac_lmstudio_default_model()
    assert model.strip() != ""


def test_lmstudio_mac_explicit_metadata_preserved():
    model = resolve_dispatch_model(
        "lmstudio-mac",
        {"model": "qwen3.5:9b-mlx"},
    )
    assert model == "qwen3.5:9b-mlx"


def test_win_preempt_uses_win_default_when_metadata_empty():
    model = resolve_dispatch_model(
        "lmstudio-mac",
        {},
        target_platform="win",
    )
    assert "27" in model or model.lower().startswith("qwen3.5-27")


def test_role_map_used_when_metadata_empty():
    model = resolve_dispatch_model(
        "lmstudio-win",
        {},
        role="executor-agent",
        specialization="python-coding",
    )
    assert "27" in model or "Qwen" in model


def test_ensure_metadata_model_injects_key():
    meta = ensure_metadata_model("lmstudio-mac", {})
    assert meta["model"] == mac_lmstudio_default_model()


def test_lmstudio_mac_whitespace_only_metadata_uses_default():
    """Whitespace-only model is treated as missing — never posted as "" to LM Studio."""
    model = resolve_dispatch_model("lmstudio-mac", {"model": "   "})
    assert model == mac_lmstudio_default_model()
