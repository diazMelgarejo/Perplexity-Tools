from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


def _expand_env_default(value: str) -> str:
    """Expand ${VAR:-default} in config strings (e.g. OLLAMA host)."""
    if not isinstance(value, str) or "${" not in value:
        return value
    m = re.match(r"^\$\{([^}:]+)(?::-([^}]*))?\}$", value.strip())
    if m:
        var, default = m.group(1), m.group(2) if m.group(2) is not None else ""
        return os.environ.get(var, default)
    return value


@dataclass
class ModelTarget:
    name: str
    backend: str  # ollama | mlx | lm-studio | perplexity | online
    device: str  # mac-studio | win-rtx3080 | shared-ollama-host | cloud
    host: str
    port: int
    context_window: Optional[int]
    roles: List[str]
    priority: int
    online: bool
    reasoning: str


class ModelRegistry:
    """
    Loads config/devices.yml, config/models.yml, config/routing.yml.
    Provides route_task(task_type, preferred_device) → ordered list of ModelTargets
    for use by the orchestrator's fallback chain.

    Top-level agents (Mac + Win) use this skill first (SKILL.md → ModelRegistry).
    Subagents use ECC-tools default logic unless explicitly overridden.
    """

    def __init__(self, config_dir: str = "config") -> None:
        self.config_dir = Path(config_dir)
        self.devices: Dict[str, Any] = self._read_yaml("devices.yml")
        self.models_cfg: Dict[str, Any] = self._read_yaml("models.yml")
        self.routing_cfg: Dict[str, Any] = self._read_yaml("routing.yml")

    def _read_yaml(self, name: str) -> Dict[str, Any]:
        path = self.config_dir / name
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    # ── model listing ─────────────────────────────────────────────────────────

    def list_models(self) -> List[ModelTarget]:
        targets: List[ModelTarget] = []
        for item in self.models_cfg.get("models", []):
            host = _expand_env_default(str(item.get("host", "")))
            targets.append(
                ModelTarget(
                    name=item["name"],
                    backend=item["backend"],
                    device=item["device"],
                    host=host,
                    port=int(item["port"]),
                    context_window=item.get("context_window"),
                    roles=item.get("roles", ["general"]),
                    priority=item.get("priority", 100),
                    online=item.get("online", False),
                    reasoning=item.get("reasoning", "general"),
                )
            )
        return sorted(targets, key=lambda x: x.priority)

    def select_for_role(
        self, role: str, preferred_device: Optional[str] = None
    ) -> List[ModelTarget]:
        candidates = [
            m for m in self.list_models() if role in m.roles
        ]
        if preferred_device:
            device_first = [m for m in candidates if m.device == preferred_device]
            others = [m for m in candidates if m.device != preferred_device]
            candidates = device_first + others
        return candidates

    # ── routing ───────────────────────────────────────────────────────────────

    def route_task(
        self, task_type: str, preferred_device: Optional[str] = None
    ) -> List[ModelTarget]:
        """
        Returns ordered fallback chain for a task_type.
        Local/preferred device models come first; online models serve as fallback.
        """
        routes = self.routing_cfg.get("routes", {})
        route = routes.get(task_type, routes.get("default", {}))
        roles: List[str] = route.get("roles", ["general"])

        ordered: List[ModelTarget] = []
        seen: set = set()
        for role in roles:
            for candidate in self.select_for_role(role, preferred_device=preferred_device):
                key = (candidate.name, candidate.device, candidate.backend)
                if key not in seen:
                    ordered.append(candidate)
                    seen.add(key)
        return ordered

    def device_info(self, device_name: str) -> Dict[str, Any]:
        return self.devices.get("devices", {}).get(device_name, {})
