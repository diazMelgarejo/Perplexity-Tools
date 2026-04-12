from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

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
        raw_devices = self._read_yaml("devices.yml")
        self.devices: Dict[str, Any] = self._normalize_devices(raw_devices)
        self.models_cfg: Dict[str, Any] = self._read_yaml("models.yml")
        self.routing_cfg: Dict[str, Any] = self._read_yaml("routing.yml")

    @staticmethod
    def _normalize_devices(raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalise devices.yml list format (v0.9.9.5+) to the dict format device_info() expects.

        Old format:  devices: {mac-studio: {...}, win-rtx3080: {...}}
        New format:  devices: [{id: "mac-studio", ...}, {id: "win-rtx3080", ...}]
        Both are handled transparently so callers never need to branch.
        """
        devs = raw.get("devices", {})
        if isinstance(devs, list):
            devs = {d["id"]: d for d in devs if "id" in d}
        return {**raw, "devices": devs}

    def _read_yaml(self, name: str) -> Dict[str, Any]:
        path = self.config_dir / name
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    # ── host resolution ────────────────────────────────────────────────────────

    def _resolve_host(self, item: Dict[str, Any]) -> str:
        """Resolve the host URL for a model entry.

        For devices with identity_method=active_tilting (win-rtx3080), derives
        the Windows IP from the local subnet at runtime so the config is portable
        across 192.168.1.x (legacy) and 192.168.254.x (current) topologies without
        any config file changes.  Explicit env-var overrides always take priority
        (LAN_GPU_IP_OVERRIDE, LM_STUDIO_WIN_ENDPOINTS — checked inside
        detect_active_tilting_ip).

        For all other devices, falls through to the usual env-var expansion.
        """
        device_name = item.get("device", "")
        dev_info = self.device_info(device_name)
        if dev_info.get("identity_method") == "active_tilting":
            from orchestrator.lan_discovery import detect_active_tilting_ip
            return detect_active_tilting_ip()
        return _expand_env_default(str(item.get("host", "")))

    # ── model listing ─────────────────────────────────────────────────────────

    def list_models(self) -> List[ModelTarget]:
        targets: List[ModelTarget] = []
        for item in self.models_cfg.get("models", []):
            host = self._resolve_host(item)
            targets.append(
                ModelTarget(
                    name=item["name"],
                    backend=item["backend"],
                    device=item["device"],
                    host=host,
                    port=int(item.get("port", 0)),
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
