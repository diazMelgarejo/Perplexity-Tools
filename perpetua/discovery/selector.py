from __future__ import annotations
from typing import Literal
from .backend import Backend, BackendKind, BackendHealth
from .registry import BackendRegistry
from .errors import NoBackendAvailableError

TaskType = Literal["coding", "reasoning", "research", "ops"]
Tier = Literal["mac", "windows", "shared"]

# Static preference table. Order matters: first match wins.
_TIER_PREF: dict[tuple[Tier, TaskType], tuple[BackendKind, ...]] = {
    ("mac",     "coding"):    (BackendKind.OLLAMA, BackendKind.LMSTUDIO),
    ("mac",     "reasoning"): (BackendKind.OLLAMA, BackendKind.LMSTUDIO),
    ("windows", "coding"):    (BackendKind.LMSTUDIO,),
    ("windows", "reasoning"): (BackendKind.LMSTUDIO,),
    ("shared",  "coding"):    (BackendKind.LMSTUDIO, BackendKind.OLLAMA),  # win-first
    ("shared",  "reasoning"): (BackendKind.OLLAMA, BackendKind.LMSTUDIO),  # mac-first
    ("shared",  "research"):  (BackendKind.LMSTUDIO, BackendKind.OLLAMA),
    ("shared",  "ops"):       (BackendKind.OLLAMA, BackendKind.LMSTUDIO),
}

# Tier-specific kinds (for hosting-machine match).
_TIER_HOSTS: dict[Tier, set[str]] = {
    "mac":     {"ollama-local", "lmstudio-mac"},
    "windows": {"lmstudio-win"},
    "shared":  set(),  # any
}


def select_backend(
    registry: BackendRegistry,
    *,
    model_hint: str | None,
    task_type: TaskType,
    target_tier: Tier,
) -> Backend:
    online = registry.online()

    # 1. model_hint always wins
    if model_hint:
        for b in online:
            if model_hint in b.models:
                return b

    # 2. tier-constrained candidates
    tier_hosts = _TIER_HOSTS[target_tier]
    candidates = [b for b in online if not tier_hosts or b.name in tier_hosts]

    # 3. apply kind preference order
    prefs = _TIER_PREF.get((target_tier, task_type), (BackendKind.OLLAMA, BackendKind.LMSTUDIO))
    for kind in prefs:
        for b in candidates:
            if b.kind is kind:
                return b

    raise NoBackendAvailableError(
        f"No online backend matches tier={target_tier} task={task_type} hint={model_hint}"
    )
