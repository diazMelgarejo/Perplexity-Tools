"""Orchestrator-side backend resolver.

Pure policy function: given a launch spec, resolve to a concrete Backend via
the discovery registry. No I/O, no env-file patching, no interactive prompts —
that operational logic lives in the top-level `agent_launcher.py` CLI.

Renamed from `orchestrator/agent_launcher.py` (2026-05-18) to remove naming
collision with the top-level CLI. Same function, same surface.
"""
from __future__ import annotations

# --- IP-aware backend resolution (added 2026-05-17, Task 4b) ---
from perpetua.discovery.registry import BackendRegistry
from perpetua.discovery.selector import select_backend
from perpetua.discovery.backend import Backend

__all__ = ["resolve_backend_for_spec"]


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
