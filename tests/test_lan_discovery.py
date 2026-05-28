from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import orchestrator.lan_discovery as lan_discovery


def _assert_timezone_aware_utc(timestamp: str) -> None:
    parsed = datetime.fromisoformat(timestamp)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() is not None
    assert parsed.utcoffset().total_seconds() == 0


def test_ai_endpoint_defaults_last_seen_to_timezone_aware_utc():
    endpoint = lan_discovery.AIEndpoint(
        host="localhost",
        port=11434,
        server_type="ollama",
        models=["qwen3:8b"],
    )

    _assert_timezone_aware_utc(endpoint.last_seen)


def test_save_discovery_state_writes_timezone_aware_timestamp(tmp_path, monkeypatch):
    state_file = tmp_path / ".state" / "lan_discovery.json"
    monkeypatch.setattr(lan_discovery, "DISCOVERY_STATE_FILE", state_file)

    discovery = lan_discovery.LANDiscovery(subnet="127.0.0.0/30", ports=[11434])
    discovery.discovered = [
        lan_discovery.AIEndpoint(
            host="localhost",
            port=11434,
            server_type="ollama",
            models=["qwen3:8b"],
        )
    ]

    discovery.save_discovery_state()

    state = json.loads(state_file.read_text())
    _assert_timezone_aware_utc(state["discovered_at"])


def test_probe_endpoint_requires_httpx(monkeypatch):
    monkeypatch.setattr(lan_discovery, "httpx", None)
    discovery = lan_discovery.LANDiscovery(subnet="127.0.0.0/30", ports=[11434])

    with pytest.raises(RuntimeError, match="httpx not installed"):
        asyncio.run(discovery._probe_endpoint("localhost", 11434))


def test_detect_local_subnet_logs_warning_on_fallback(monkeypatch, caplog):
    import socket

    monkeypatch.setattr(socket, "gethostbyname", lambda _hostname: (_ for _ in ()).throw(OSError("dns down")))
    caplog.set_level("WARNING", logger="orchestrator.lan_discovery")

    subnet = lan_discovery.LANDiscovery(subnet=None, ports=[11434]).subnet

    assert subnet == "192.168.1.0/24"
    assert "Failed to auto-detect local subnet" in caplog.text


def test_select_windows_lmstudio_host_skips_mac_mirror_in_scan_order():
    hosts = ["192.168.254.105", "192.168.254.108"]
    picked = lan_discovery._select_windows_lmstudio_host(
        hosts, local_ip="192.168.254.105", preferred_win_ip=None
    )
    assert picked == "192.168.254.108"


def test_select_windows_lmstudio_host_prefers_openclaw_windows_ip():
    hosts = ["192.168.254.105", "192.168.254.108", "192.168.254.110"]
    picked = lan_discovery._select_windows_lmstudio_host(
        hosts,
        local_ip="192.168.254.105",
        preferred_win_ip="192.168.254.108",
    )
    assert picked == "192.168.254.108"


def test_detect_active_tilting_ip_env_override_bypasses_cache(monkeypatch):
    monkeypatch.setattr(lan_discovery, "_cached_active_tilting_url", "http://192.168.254.1")
    monkeypatch.setenv("LM_STUDIO_WIN_ENDPOINTS", "http://10.0.0.50:1234")

    assert lan_discovery.detect_active_tilting_ip() == "http://10.0.0.50:1234"


def test_detect_active_tilting_ip_caches_probe_result(monkeypatch):
    monkeypatch.delenv("LAN_GPU_IP_OVERRIDE", raising=False)
    monkeypatch.delenv("LM_STUDIO_WIN_ENDPOINTS", raising=False)
    monkeypatch.setattr(lan_discovery, "_cached_active_tilting_url", None)

    scan_calls = {"n": 0}

    class FakeNetworkAutoConfig:
        preferred_ips = {"Windows": "192.168.254.108"}

        def get_working_local_ip(self) -> str:
            return "192.168.254.105"

        def discover_lan_agents(self, **kwargs):
            scan_calls["n"] += 1
            return {"lmstudio": ["192.168.254.105", "192.168.254.108"]}

    monkeypatch.setattr(
        "packages.net_utils.network_autoconfig.NetworkAutoConfig",
        FakeNetworkAutoConfig,
    )

    first = lan_discovery.detect_active_tilting_ip()
    second = lan_discovery.detect_active_tilting_ip()

    assert first == second == "http://192.168.254.108"
    assert scan_calls["n"] == 1


def test_model_registry_resolves_active_tilting_once(monkeypatch, tmp_path):
    from orchestrator.model_registry import ModelRegistry

    calls = {"n": 0}

    def fake_detect() -> str:
        calls["n"] += 1
        return "http://192.168.254.108"

    monkeypatch.setattr(lan_discovery, "detect_active_tilting_ip", fake_detect)
    monkeypatch.setattr(lan_discovery, "_cached_active_tilting_url", None)

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "devices.yml").write_text(
        """
version: "0"
devices:
  - id: win-rtx3080
    identity_method: active_tilting
"""
    )
    (config_dir / "models.yml").write_text(
        """
models:
  - name: win-a
    backend: lm-studio
    device: win-rtx3080
    host: unused
    port: 1234
    roles: [coding]
  - name: win-b
    backend: lm-studio
    device: win-rtx3080
    host: unused
    port: 1234
    roles: [executor]
"""
    )
    (config_dir / "routing.yml").write_text("routes: {}\n")

    registry = ModelRegistry(config_dir=str(config_dir))
    models = registry.list_models()

    assert calls["n"] == 1
    assert all(m.host == "http://192.168.254.108" for m in models)
