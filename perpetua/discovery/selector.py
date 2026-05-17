from __future__ import annotations
from typing import Literal
from .backend import Backend, BackendKind, BackendHealth
from .registry import BackendRegistry
from .errors import NoBackendAvailableError

TaskType = Literal["coding", "reasoning", "research", "ops"]
Tier = Literal["mac", "windows", "shared"]

# HARDWARE POLICY: lmstudio-mac is a MIRROR that proxies Win models over the LAN.
# The Mac hardware CANNOT run heavy Win-only models (e.g. qwen3.5-27b on RTX 3080).
# Exclude it from inference dispatch to prevent double-barrel GPU contention.
_MIRROR_BACKENDS: frozenset[str] = frozenset({"lmstudio-mac"})

# Static preference table. Order matters: first match wins.
_TIER_PREF: dict[tuple[Tier, TaskType], tuple[BackendKind, ...]] = {
    ("mac",     "coding"):    (BackendKind.OLLAMA,),                       # Ollama-only on Mac
    ("mac",     "reasoning"): (BackendKind.OLLAMA,),                       # Ollama-only on Mac
    ("windows", "coding"):    (BackendKind.LMSTUDIO,),
    ("windows", "reasoning"): (BackendKind.LMSTUDIO,),
    ("shared",  "coding"):    (BackendKind.LMSTUDIO, BackendKind.OLLAMA),  # win-first
    ("shared",  "reasoning"): (BackendKind.OLLAMA, BackendKind.LMSTUDIO),  # mac-first (Ollama)
    ("shared",  "research"):  (BackendKind.LMSTUDIO, BackendKind.OLLAMA),
    ("shared",  "ops"):       (BackendKind.OLLAMA, BackendKind.LMSTUDIO),
}

# Tier-specific hosts. Mac only routes to ollama-local (never lmstudio-mac — mirror only).
_TIER_HOSTS: dict[Tier, set[str]] = {
    "mac":     {"ollama-local"},
    "windows": {"lmstudio-win"},
    "shared":  set(),  # any non-mirror (see _MIRROR_BACKENDS filter below)
}


def select_backend(
    registry: BackendRegistry,
    *,
    model_hint: str | None,
    task_type: TaskType,
    target_tier: Tier,
) -> Backend:
    online = registry.online()

    # 1. model_hint always wins (mirrors excluded — they cannot run heavy Win-only models)
    if model_hint:
        for b in online:
            if model_hint in b.models and b.name not in _MIRROR_BACKENDS:
                return b

    # 2. tier-constrained candidates, never including mirrors
    tier_hosts = _TIER_HOSTS[target_tier]
    candidates = [
        b for b in online
        if (not tier_hosts or b.name in tier_hosts)
        and b.name not in _MIRROR_BACKENDS
    ]

    # 3. apply kind preference order
    prefs = _TIER_PREF.get((target_tier, task_type), (BackendKind.OLLAMA, BackendKind.LMSTUDIO))
    for kind in prefs:
        for b in candidates:
            if b.kind is kind:
                return b

    raise NoBackendAvailableError(
        f"No online backend matches tier={target_tier} task={task_type} hint={model_hint}"
    )
