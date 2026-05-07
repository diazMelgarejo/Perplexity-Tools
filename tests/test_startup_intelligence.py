"""tests/test_startup_intelligence.py
--------------------------------------
Unit tests for orchestrator/startup_intelligence.py

All tests run fully offline — no network, no filesystem I/O.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestrator.startup_intelligence import (
    SCENARIO_TABLE,
    StartupScenario,
    build_routing_hints,
    classify_scenario,
)


# ---------------------------------------------------------------------------
# classify_scenario
# ---------------------------------------------------------------------------

def test_classify_full_distributed():
    # mac_ok + lms_ok → FULL_DISTRIBUTED
    assert classify_scenario(True, False, False, True) == StartupScenario.FULL_DISTRIBUTED


def test_classify_mac_ollama_only():
    assert classify_scenario(True, False, False, False) == StartupScenario.MAC_OLLAMA_ONLY


def test_classify_mac_lms_only():
    assert classify_scenario(False, True, False, False) == StartupScenario.MAC_LMS_ONLY


def test_classify_mac_dual():
    assert classify_scenario(True, True, False, False) == StartupScenario.MAC_DUAL


def test_classify_cloud_only():
    assert classify_scenario(False, False, False, False, cloud_ok=True) == StartupScenario.CLOUD_ONLY


def test_classify_fully_offline():
    assert classify_scenario(False, False, False, False) == StartupScenario.FULLY_OFFLINE


def test_classify_win_only_no_mac():
    # Win-without-Mac is not a valid manager scenario → FULLY_OFFLINE (no cloud key)
    assert classify_scenario(False, False, True, False) == StartupScenario.FULLY_OFFLINE


def test_classify_all_backends_up():
    # All 4 backends up → still FULL_DISTRIBUTED (mac_any AND win_any)
    assert classify_scenario(True, True, True, True) == StartupScenario.FULL_DISTRIBUTED


# ---------------------------------------------------------------------------
# build_routing_hints
# ---------------------------------------------------------------------------

def test_routing_hints_empty_history():
    hints = build_routing_hints([])
    assert hints["win_ip_hint"] is None
    assert hints["suggested_timeout_win_lms"] == 3


def test_routing_hints_fast_backend():
    history = [
        {"win_ip": "192.168.1.104", "win_lms_latency_ms": 400, "mac_ol_latency_ms": 12},
        {"win_ip": "192.168.1.104", "win_lms_latency_ms": 600, "mac_ol_latency_ms": 15},
    ]
    hints = build_routing_hints(history)
    assert hints["win_ip_hint"] == "192.168.1.104"
    assert hints["suggested_timeout_win_lms"] == 3   # p50 = 500 < 2000


def test_routing_hints_slow_backend():
    history = [
        {"win_ip": "192.168.1.104", "win_lms_latency_ms": 2500},
        {"win_ip": "192.168.1.104", "win_lms_latency_ms": 3100},
    ]
    hints = build_routing_hints(history)
    assert hints["suggested_timeout_win_lms"] == 6   # p50 = 2800 > 2000


def test_routing_hints_uses_last_5():
    # 7 entries — only last 5 used for p50
    history = [{"win_lms_latency_ms": 5000}] * 2 + [{"win_lms_latency_ms": 400}] * 5
    hints = build_routing_hints(history)
    assert hints["suggested_timeout_win_lms"] == 3   # last 5 are all fast


def test_routing_hints_single_entry_no_p50():
    # Only 1 latency sample — not enough for median, p50 must be None
    history = [{"win_ip": "10.0.0.1", "win_lms_latency_ms": 5000}]
    hints = build_routing_hints(history)
    assert hints["win_lms_p50_ms"] is None
    assert hints["suggested_timeout_win_lms"] == 3   # unknown → safe default


def test_routing_hints_mac_latency():
    history = [
        {"mac_ol_latency_ms": 10},
        {"mac_ol_latency_ms": 20},
    ]
    hints = build_routing_hints(history)
    assert hints["mac_ol_p50_ms"] == 15
    assert hints["suggested_timeout_mac_ol"] == 3   # always 3


def test_scenario_table_completeness():
    for scenario in StartupScenario:
        assert scenario in SCENARIO_TABLE, f"{scenario} missing from SCENARIO_TABLE"


def test_fallback_chain_ordering():
    # In FULL_DISTRIBUTED, windows-lmstudio must be first coder option
    chain = SCENARIO_TABLE[StartupScenario.FULL_DISTRIBUTED]
    assert chain.coder_backends[0] == "windows-lmstudio"


def test_cloud_only_chain():
    chain = SCENARIO_TABLE[StartupScenario.CLOUD_ONLY]
    assert chain.cloud_ok is True
    assert chain.coder_backends == ["cloud-api"]


def test_fully_offline_chain():
    chain = SCENARIO_TABLE[StartupScenario.FULLY_OFFLINE]
    assert chain.manager_backends == []
    assert chain.coder_backends == []
    assert chain.cloud_ok is False


def test_routing_hints_malformed_entry():
    # Malformed entries must be silently skipped, not crash
    history = [{"bad_key": "bad_value"}, {"win_ip": "1.2.3.4", "win_lms_latency_ms": 500}]
    hints = build_routing_hints(history)
    assert hints["win_ip_hint"] == "1.2.3.4"


def test_routing_hints_never_raises_on_garbage():
    # Completely broken input — must return safe defaults
    hints = build_routing_hints([None, 42, "string"])  # type: ignore[arg-type]
    assert hints["win_ip_hint"] is None
    assert hints["suggested_timeout_win_lms"] == 3
