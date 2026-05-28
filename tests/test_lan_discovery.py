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


# ── detect_active_tilting_ip() tests ─────────────────────────────────────────


def test_detect_active_tilting_ip_env_override_with_http_prefix(monkeypatch):
    """LAN_GPU_IP_OVERRIDE with http:// prefix is returned as-is."""
    monkeypatch.setenv("LAN_GPU_IP_OVERRIDE", "http://10.0.1.200")
    monkeypatch.delenv("LM_STUDIO_WIN_ENDPOINTS", raising=False)
    result = lan_discovery.detect_active_tilting_ip()
    assert result == "http://10.0.1.200"


def test_detect_active_tilting_ip_env_override_without_http_prefix(monkeypatch):
    """LAN_GPU_IP_OVERRIDE without http:// prefix gets http:// prepended."""
    monkeypatch.setenv("LAN_GPU_IP_OVERRIDE", "192.168.1.50")
    monkeypatch.delenv("LM_STUDIO_WIN_ENDPOINTS", raising=False)
    result = lan_discovery.detect_active_tilting_ip()
    assert result == "http://192.168.1.50"


def test_detect_active_tilting_ip_lm_studio_win_endpoints_with_http(monkeypatch):
    """LM_STUDIO_WIN_ENDPOINTS with http:// prefix is returned as-is."""
    monkeypatch.delenv("LAN_GPU_IP_OVERRIDE", raising=False)
    monkeypatch.setenv("LM_STUDIO_WIN_ENDPOINTS", "http://192.168.254.108:1234")
    result = lan_discovery.detect_active_tilting_ip()
    assert result == "http://192.168.254.108:1234"


def test_detect_active_tilting_ip_lm_studio_win_endpoints_without_http(monkeypatch):
    """LM_STUDIO_WIN_ENDPOINTS without http:// prefix gets http:// prepended."""
    monkeypatch.delenv("LAN_GPU_IP_OVERRIDE", raising=False)
    monkeypatch.setenv("LM_STUDIO_WIN_ENDPOINTS", "192.168.254.108")
    result = lan_discovery.detect_active_tilting_ip()
    assert result == "http://192.168.254.108"


def test_detect_active_tilting_ip_lan_gpu_override_takes_priority(monkeypatch):
    """LAN_GPU_IP_OVERRIDE takes priority over LM_STUDIO_WIN_ENDPOINTS."""
    monkeypatch.setenv("LAN_GPU_IP_OVERRIDE", "http://override.example.com")
    monkeypatch.setenv("LM_STUDIO_WIN_ENDPOINTS", "http://should-not-be-returned.example.com")
    result = lan_discovery.detect_active_tilting_ip()
    assert result == "http://override.example.com"


def test_detect_active_tilting_ip_socket_detection_current_subnet(monkeypatch):
    """Socket-based detection derives .103 on the 192.168.254.x subnet."""
    import socket as _socket

    monkeypatch.delenv("LAN_GPU_IP_OVERRIDE", raising=False)
    monkeypatch.delenv("LM_STUDIO_WIN_ENDPOINTS", raising=False)

    class _FakeSocket:
        def connect(self, addr):
            pass

        def getsockname(self):
            return ("192.168.254.5", 0)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(_socket, "socket", lambda *a, **kw: _FakeSocket())
    result = lan_discovery.detect_active_tilting_ip()
    assert result == "http://192.168.254.103"


def test_detect_active_tilting_ip_socket_detection_legacy_subnet(monkeypatch):
    """Socket-based detection derives .103 on a legacy 192.168.1.x subnet."""
    import socket as _socket

    monkeypatch.delenv("LAN_GPU_IP_OVERRIDE", raising=False)
    monkeypatch.delenv("LM_STUDIO_WIN_ENDPOINTS", raising=False)

    class _FakeSocket:
        def connect(self, addr):
            pass

        def getsockname(self):
            return ("192.168.1.42", 0)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(_socket, "socket", lambda *a, **kw: _FakeSocket())
    result = lan_discovery.detect_active_tilting_ip()
    assert result == "http://192.168.1.103"


def test_detect_active_tilting_ip_socket_detection_arbitrary_subnet(monkeypatch):
    """Socket-based detection always appends .103 regardless of subnet prefix."""
    import socket as _socket

    monkeypatch.delenv("LAN_GPU_IP_OVERRIDE", raising=False)
    monkeypatch.delenv("LM_STUDIO_WIN_ENDPOINTS", raising=False)

    class _FakeSocket:
        def connect(self, addr):
            pass

        def getsockname(self):
            return ("10.20.30.1", 0)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(_socket, "socket", lambda *a, **kw: _FakeSocket())
    result = lan_discovery.detect_active_tilting_ip()
    assert result == "http://10.20.30.103"


def test_detect_active_tilting_ip_socket_exception_falls_back(monkeypatch):
    """When the socket call raises, the hardcoded fallback URL is returned."""
    import socket as _socket

    monkeypatch.delenv("LAN_GPU_IP_OVERRIDE", raising=False)
    monkeypatch.delenv("LM_STUDIO_WIN_ENDPOINTS", raising=False)

    def _raise(*args, **kwargs):
        raise OSError("network unavailable")

    monkeypatch.setattr(_socket, "socket", _raise)
    result = lan_discovery.detect_active_tilting_ip()
    assert result == "http://192.168.254.103"


def test_detect_active_tilting_ip_socket_exception_logs_warning(monkeypatch, caplog):
    """Socket failure emits a warning-level log message."""
    import socket as _socket

    monkeypatch.delenv("LAN_GPU_IP_OVERRIDE", raising=False)
    monkeypatch.delenv("LM_STUDIO_WIN_ENDPOINTS", raising=False)
    monkeypatch.setattr(_socket, "socket", lambda *a, **kw: (_ for _ in ()).throw(OSError("no route")))
    caplog.set_level("WARNING", logger="orchestrator.lan_discovery")

    lan_discovery.detect_active_tilting_ip()

    assert "192.168.254.103" in caplog.text


def test_detect_active_tilting_ip_empty_env_vars_use_socket(monkeypatch):
    """Empty string env vars are treated as unset; socket detection is used."""
    import socket as _socket

    monkeypatch.setenv("LAN_GPU_IP_OVERRIDE", "")
    monkeypatch.setenv("LM_STUDIO_WIN_ENDPOINTS", "")

    class _FakeSocket:
        def connect(self, addr):
            pass

        def getsockname(self):
            return ("172.16.0.10", 0)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(_socket, "socket", lambda *a, **kw: _FakeSocket())
    result = lan_discovery.detect_active_tilting_ip()
    assert result == "http://172.16.0.103"


def test_detect_active_tilting_ip_result_has_no_port_or_path(monkeypatch):
    """Socket-based result is a bare base URL — no port, no trailing path."""
    import socket as _socket

    monkeypatch.delenv("LAN_GPU_IP_OVERRIDE", raising=False)
    monkeypatch.delenv("LM_STUDIO_WIN_ENDPOINTS", raising=False)

    class _FakeSocket:
        def connect(self, addr):
            pass

        def getsockname(self):
            return ("192.168.254.5", 0)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(_socket, "socket", lambda *a, **kw: _FakeSocket())
    result = lan_discovery.detect_active_tilting_ip()
    # Must not contain a port number or path segment
    assert result.count(":") == 1  # only the "http:" colon
    assert result.endswith(".103")
