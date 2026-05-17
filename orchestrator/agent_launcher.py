"""Orchestrator-side agent launcher shim.

Bridges launch specs to the discovery registry so callers no longer hardcode
LMSTUDIO_WIN_URL or OLLAMA_BASE. Honors caller-forced overrides for direct-IP
selection.
"""
from __future__ import annotations

# --- IP-aware backend resolution (added 2026-05-17, Task 4b) ---
from perpetua.discovery.registry import BackendRegistry
from perpetua.discovery.selector import select_backend
from perpetua.discovery.backend import Backend


def resolve_backend_for_spec(registry: BackendRegistry, spec: dict) -> Backend:
    """Resolve a launch spec to a concrete Backend.
    Honors spec['base_url_override'] for caller-forced direct-IP selection.
    Otherwise consults the registry's selector.
    """
    override = spec.get("base_url_override")
    if override:
        for b in registry.all():
            if b.base_url == override:
                return b
        # Caller forced a URL we don't know about — synthesize an unverified Backend.
        return Backend(name="adhoc", base_url=override,
                       kind=spec.get("kind", "lmstudio"),  # type: ignore[arg-type]
                       models=(), health="unknown", last_seen=None)  # type: ignore[arg-type]
    return select_backend(
        registry,
        model_hint=spec.get("model_hint"),
        task_type=spec.get("task_type", "reasoning"),
        target_tier=spec.get("target_tier", "shared"),
    )
