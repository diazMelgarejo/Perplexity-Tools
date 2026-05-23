"""Explicit dispatch model IDs — never rely on LM Studio's "loaded model" fallback.

``lmstudio-mac`` is a LAN *mirror* (see ``config/model_hardware_policy.yml``).
Posting ``model: ""`` to its API lets the server pick whatever is loaded locally,
which may be a ``windows_only`` GGUF proxied from Win — violating anti-mirror policy
and risking double-barrel GPU use.

All inference paths must call :func:`resolve_dispatch_model` so affinity checks and
HTTP payloads use the same explicit model id.
"""

from __future__ import annotations

import os
from typing import Any, Optional

# Backends that send ``model`` to a local/cloud inference API.
_BACKENDS_WITH_MODEL: frozenset[str] = frozenset(
    {"ollama", "ollama-mac", "lmstudio-mac", "lmstudio-win", "mlx"}
)

# lmstudio-mac must never post an empty model string (anti-mirror invariant).
_NEVER_EMPTY_MODEL_BACKENDS: frozenset[str] = frozenset({"lmstudio-mac"})


def mac_lmstudio_default_model() -> str:
    return (
        os.getenv("MAC_LMS_MODEL")
        or os.getenv("LMS_MAC_MODEL")
        or "Qwen3.5-9B-MLX-4bit"
    )


def ollama_mac_default_model() -> str:
    return os.getenv("OLLAMA_MAC_MODEL", "qwen3.5:9b-nvfp4")


def lmstudio_win_default_model() -> str:
    return os.getenv(
        "WINDOWS_CODER_MODEL",
        "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2",
    )


def backend_requires_dispatch_model(backend: str) -> bool:
    return backend.lower().strip() in _BACKENDS_WITH_MODEL


def backend_never_empty_model(backend: str) -> bool:
    return backend.lower().strip() in _NEVER_EMPTY_MODEL_BACKENDS


def _normalize_backend(backend: str) -> str:
    return backend.lower().strip()


def _role_mapped_model(
    backend: str,
    *,
    role: Optional[str],
    specialization: Optional[str],
    target_platform: Optional[str],
) -> Optional[str]:
    if not role:
        return None
    # Import here to avoid circular import (worker_registry imports this module).
    from orchestrator.worker_registry import resolve_role_backend

    pair = resolve_role_backend(role, specialization)
    if pair is None:
        return None
    mapped_backend, mapped_model = pair
    mapped_backend = _normalize_backend(mapped_backend)
    norm = _normalize_backend(backend)
    if target_platform == "win" and mapped_backend == "lmstudio-win":
        return mapped_model
    if mapped_backend == norm or (norm in {"ollama", "ollama-mac"} and mapped_backend == "ollama"):
        return mapped_model
    return None


def resolve_dispatch_model(
    backend: str,
    metadata: dict[str, Any] | None = None,
    *,
    role: Optional[str] = None,
    specialization: Optional[str] = None,
    target_platform: Optional[str] = None,
) -> str:
    """Return the model id that will be sent to the inference API.

    Priority:
      1. Non-empty ``metadata["model"]``
      2. ``ROLE_BACKEND_MAP`` when ``role`` matches the resolved backend
      3. Platform-aware default (``target_platform="win"`` for Windows preemption)
      4. Backend default (never ``""`` for ``lmstudio-mac``)

    Raises:
        ValueError: unknown backend or ``lmstudio-mac`` would remain without a model.
    """
    meta = metadata or {}
    explicit = str(meta.get("model") or "").strip()
    if explicit:
        return explicit

    from_role = _role_mapped_model(
        backend,
        role=role,
        specialization=specialization,
        target_platform=target_platform,
    )
    if from_role:
        return from_role

    norm = _normalize_backend(backend)
    plat = (target_platform or "").lower().strip()
    if plat == "win" or norm == "lmstudio-win":
        return lmstudio_win_default_model()
    if norm in {"ollama", "ollama-mac", "mlx"}:
        return ollama_mac_default_model()
    if norm == "lmstudio-mac":
        default = mac_lmstudio_default_model()
        if not default.strip():
            raise ValueError(
                "lmstudio-mac requires an explicit model id; empty MAC_LMS_MODEL is forbidden "
                "(anti-mirror: never use LM Studio 'loaded model' fallback)."
            )
        return default

    raise ValueError(f"No dispatch model default for backend {backend!r}")


def ensure_metadata_model(
    backend: str,
    metadata: dict[str, Any] | None,
    *,
    role: Optional[str] = None,
    specialization: Optional[str] = None,
    target_platform: Optional[str] = None,
) -> dict[str, Any]:
    """Return metadata with ``model`` set to the resolved dispatch id when missing."""
    out = dict(metadata or {})
    if str(out.get("model") or "").strip():
        return out
    out["model"] = resolve_dispatch_model(
        backend,
        out,
        role=role,
        specialization=specialization,
        target_platform=target_platform,
    )
    return out
