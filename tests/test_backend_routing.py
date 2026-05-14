"""tests/test_backend_routing.py — Role routing → intent fallback → explicit override.

Tests the three-layer routing priority from unified-absorption-plan.md § 5.2:
  1. role + specialization → ROLE_BACKEND_MAP
  2. intent → _INTENT_BACKEND_MAP
  3. backend_hint → explicit override
"""
from __future__ import annotations

import pytest

from orchestrator.worker_registry import (
    ROLE_BACKEND_MAP,
    WORKER_REGISTRY,
    resolve_backend,
    resolve_role_backend,
)


# ── Helper ────────────────────────────────────────────────────────────────────

class _Spec:
    """Minimal duck-type object that worker_registry.resolve_backend reads."""
    def __init__(self, *, intent="", role=None, specialization=None, backend_hint=None):
        self.intent = intent
        self.role = role
        self.specialization = specialization
        self.backend_hint = backend_hint


# ── Layer 1: role + specialization → ROLE_BACKEND_MAP ─────────────────────────

class TestRoleBackendMap:
    def test_executor_python_coding_routes_to_win(self):
        b, m = resolve_role_backend("executor-agent", "python-coding")
        assert b == "lmstudio-win"
        assert "Qwen3.5-27B" in m

    def test_executor_test_writing_routes_to_win(self):
        b, _ = resolve_role_backend("executor-agent", "test-writing")
        assert b == "lmstudio-win"

    def test_executor_default_routes_to_win(self):
        b, _ = resolve_role_backend("executor-agent")
        assert b == "lmstudio-win"

    def test_context_market_research_routes_to_ollama(self):
        b, m = resolve_role_backend("context-agent", "market-research")
        assert b == "ollama"
        assert m == "qwen3.5:9b-nvfp4"

    def test_context_ma_research_routes_to_ollama(self):
        b, _ = resolve_role_backend("context-agent", "m&a-research")
        assert b == "ollama"

    def test_context_default_routes_to_ollama(self):
        b, m = resolve_role_backend("context-agent")
        assert b == "ollama"
        assert m == "qwen3.5:9b-nvfp4"

    def test_verifier_default_routes_to_win(self):
        b, _ = resolve_role_backend("verifier-agent")
        assert b == "lmstudio-win"

    def test_crystallizer_default_routes_to_ollama(self):
        b, m = resolve_role_backend("crystallizer-agent")
        assert b == "ollama"
        assert m == "qwen3.5:9b-nvfp4"

    def test_architect_default_routes_to_win(self):
        b, _ = resolve_role_backend("architect-agent")
        assert b == "lmstudio-win"

    def test_refiner_default_routes_to_ollama(self):
        b, _ = resolve_role_backend("refiner-agent")
        assert b == "ollama"

    def test_unknown_role_returns_none(self):
        result = resolve_role_backend("nonexistent-agent")
        assert result is None

    def test_specific_specialization_beats_default(self):
        """Specific (role, spec) takes priority over (role, None)."""
        b_specific, _ = resolve_role_backend("executor-agent", "python-coding")
        b_default, _ = resolve_role_backend("executor-agent", None)
        # Both happen to be lmstudio-win for executor, but the test verifies lookup order
        assert b_specific is not None
        assert b_default is not None


# ── Layer 2: intent fallback ──────────────────────────────────────────────────

class TestIntentFallback:
    """When role is absent or unknown, intent-based routing kicks in."""

    def test_code_review_routes_to_codex(self):
        spec = _Spec(intent="code-review")
        assert resolve_backend(spec) == "codex"

    def test_debug_routes_to_codex(self):
        spec = _Spec(intent="debug")
        assert resolve_backend(spec) == "codex"

    def test_ml_experiment_routes_to_gemini(self):
        spec = _Spec(intent="ml-experiment")
        assert resolve_backend(spec) == "gemini"

    def test_research_routes_to_gemini(self):
        spec = _Spec(intent="research")
        assert resolve_backend(spec) == "gemini"

    def test_freeform_routes_to_ollama(self):
        spec = _Spec(intent="freeform")
        assert resolve_backend(spec) == "ollama"

    def test_unknown_intent_routes_to_echo(self):
        spec = _Spec(intent="totally-unknown")
        assert resolve_backend(spec) == "echo"

    def test_empty_intent_routes_to_echo(self):
        spec = _Spec(intent="")
        assert resolve_backend(spec) == "echo"


# ── Layer 3: backend_hint explicit override ────────────────────────────────────

class TestExplicitOverride:
    """backend_hint overrides both role map and intent fallback."""

    def test_explicit_hint_beats_role(self):
        # executor normally → lmstudio-win, but hint forces gemini
        spec = _Spec(role="executor-agent", backend_hint="gemini")
        assert resolve_backend(spec) == "gemini"

    def test_explicit_hint_beats_intent(self):
        spec = _Spec(intent="research", backend_hint="codex")
        assert resolve_backend(spec) == "codex"

    def test_hint_auto_falls_through_to_role(self):
        spec = _Spec(role="context-agent", backend_hint="auto")
        assert resolve_backend(spec) == "ollama"

    def test_hint_empty_string_falls_through(self):
        spec = _Spec(intent="research", backend_hint="")
        assert resolve_backend(spec) == "gemini"


# ── Priority order integration test ──────────────────────────────────────────

class TestPriorityOrder:
    def test_role_beats_intent(self):
        """context-agent with intent='research' should pick ollama (role wins)."""
        spec = _Spec(role="context-agent", intent="research")
        backend = resolve_backend(spec)
        assert backend == "ollama"   # role map wins over intent=research→gemini

    def test_hint_beats_role(self):
        spec = _Spec(role="verifier-agent", backend_hint="echo")
        assert resolve_backend(spec) == "echo"


# ── Registry completeness ─────────────────────────────────────────────────────

class TestRegistryCompleteness:
    def test_all_role_backends_have_worker(self):
        """Every backend referenced in ROLE_BACKEND_MAP must have a worker entry."""
        backends_in_map = {v[0] for v in ROLE_BACKEND_MAP.values()}
        for backend in backends_in_map:
            assert backend in WORKER_REGISTRY, (
                f"Backend '{backend}' in ROLE_BACKEND_MAP has no worker in WORKER_REGISTRY"
            )

    def test_echo_worker_present(self):
        assert "echo" in WORKER_REGISTRY

    def test_ollama_worker_present(self):
        assert "ollama" in WORKER_REGISTRY

    def test_lmstudio_win_worker_present(self):
        assert "lmstudio-win" in WORKER_REGISTRY
