"""Hardware-bound model affinity policy helpers.

The canonical policy lives at ``config/model_hardware_policy.yml``.  This module
is deliberately small and side-effect-light so both runtime paths and tests can
use the same enforcement rules without importing the full orchestrator stack.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:  # PyYAML is a declared PT dependency, but keep a tiny fallback for scripts.
    import yaml  # type: ignore
except Exception:  # pragma: no cover - exercised only in stripped environments
    yaml = None


class HardwareAffinityError(RuntimeError):
    """
    Raised when a model is assigned to hardware it cannot safely run on.

    API callers should convert this to HTTP 400 HARDWARE_MISMATCH.  Runtime
    launchers should treat it as a hard kill-switch for the unsafe assignment.
    """


_POLICY_CACHE: dict[str, Any] | None = None


def _simple_policy_parse(text: str) -> dict[str, list[str]]:
    """Parse the small policy YAML shape without requiring PyYAML."""
    parsed: dict[str, list[str]] = {"windows_only": [], "mac_only": [], "shared": []}
    current: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.endswith(":") and not stripped.startswith("-"):
            key = stripped[:-1]
            current = key if key in parsed else None
            continue
        if current and stripped.startswith("-"):
            value = stripped[1:].strip().strip('"').strip("'")
            if value:
                parsed[current].append(value)
    return parsed


def load_policy(policy_path: Path | None = None, *, force_reload: bool = False) -> dict[str, Any]:
    """Load and cache the hardware policy YAML."""
    global _POLICY_CACHE
    if _POLICY_CACHE is not None and not force_reload and policy_path is None:
        return _POLICY_CACHE

    if policy_path is None:
        policy_path = Path(__file__).resolve().parent.parent / "config" / "model_hardware_policy.yml"

    text = policy_path.read_text(encoding="utf-8")
    if yaml is not None:
        loaded = yaml.safe_load(text) or {}
    else:
        loaded = _simple_policy_parse(text)

    policy = {
        "windows_only": list(loaded.get("windows_only", []) or []),
        "mac_only": list(loaded.get("mac_only", []) or []),
        "shared": list(loaded.get("shared", []) or []),
    }
    if policy_path == Path(__file__).resolve().parent.parent / "config" / "model_hardware_policy.yml":
        _POLICY_CACHE = policy
    return policy


def forbidden_models_for_platform(platform: str, policy: dict[str, Any] | None = None) -> set[str]:
    """Return lower-cased model IDs forbidden on ``platform``."""
    policy = policy or load_policy()
    normalized = platform.lower().strip()
    if normalized in {"mac", "macos", "darwin", "apple", "mac-studio", "lmstudio-mac"}:
        return {str(m).lower() for m in policy.get("windows_only", [])}
    if normalized in {"win", "windows", "win32", "win-rtx3080", "lmstudio-win", "ollama-win"}:
        return {str(m).lower() for m in policy.get("mac_only", [])}
    return set()


def filter_models_for_platform(
    models: list[str],
    platform: str,
    policy: dict[str, Any] | None = None,
) -> list[str]:
    """Remove models forbidden on the given hardware platform."""
    forbidden = forbidden_models_for_platform(platform, policy)
    return [m for m in models if str(m).lower() not in forbidden]


def check_affinity(model_id: str, platform: str, policy: dict[str, Any] | None = None) -> None:
    """Raise ``HardwareAffinityError`` if ``model_id`` is forbidden on ``platform``."""
    policy = policy or load_policy()
    model_lower = model_id.lower()
    normalized = platform.lower().strip()
    if normalized in {"mac", "macos", "darwin", "apple", "mac-studio", "lmstudio-mac"}:
        forbidden = {m.lower() for m in policy.get("windows_only", [])}
        if model_lower in forbidden:
            raise HardwareAffinityError(
                f"[alphaclaw] Fatal: '{model_id}' is NEVER_MAC. "
                "Assign to lmstudio-win only."
            )
    elif normalized in {"win", "windows", "win32", "win-rtx3080", "lmstudio-win", "ollama-win"}:
        forbidden = {m.lower() for m in policy.get("mac_only", [])}
        if model_lower in forbidden:
            raise HardwareAffinityError(
                f"[alphaclaw] Fatal: '{model_id}' is NEVER_WIN. "
                "Assign to lmstudio-mac only."
            )


def expected_platform_for_model(model_id: str, policy: dict[str, Any] | None = None) -> str | None:
    """Return the required platform for a known constrained model, if any."""
    policy = policy or load_policy()
    model_lower = model_id.lower()
    if model_lower in {m.lower() for m in policy.get("windows_only", [])}:
        return "win"
    if model_lower in {m.lower() for m in policy.get("mac_only", [])}:
        return "mac"
    return None