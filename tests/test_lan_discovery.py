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
        host="127.0.0.1",
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
            host="127.0.0.1",
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
        asyncio.run(discovery._probe_endpoint("127.0.0.1", 11434))
