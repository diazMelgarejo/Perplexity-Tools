"""test_cost_guard.py — Unit tests for orchestrator/cost_guard.py

Tests CostGuard budget enforcement, spend tracking, alert thresholds,
24h auto-reset, and snapshot output.
Runs offline — no Ollama, no external API calls required.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from orchestrator.cost_guard import CostGuard


@pytest.fixture
def guard(tmp_path):
    """Fresh CostGuard with 25.0 daily budget backed by a temp dir."""
    return CostGuard(state_dir=str(tmp_path / ".state"))


class TestCanSpend:
    def test_can_spend_within_budget(self, guard):
        assert guard.can_spend(10.0) is True

    def test_can_spend_exact_budget(self, guard):
        # spend 24.99 first, then check if 0.01 is allowed
        guard.record_spend(24.99)
        assert guard.can_spend(0.01) is True

    def test_cannot_spend_over_budget(self, guard):
        guard.record_spend(25.0)
        assert guard.can_spend(0.01) is False

    def test_cannot_spend_when_already_at_limit(self, guard):
        guard.record_spend(25.0)
        assert guard.can_spend(0.0) is True  # exactly at limit is still allowed
        assert guard.can_spend(1.0) is False

    def test_custom_budget(self, tmp_path):
        g = CostGuard(state_dir=str(tmp_path / ".state2"))
        g.set_budget(10.0)
        assert g.can_spend(9.99) is True
        assert g.can_spend(10.01) is False


class TestRecordSpend:
    def test_record_spend_accumulates(self, guard):
        guard.record_spend(5.0)
        guard.record_spend(3.0)
        snap = guard.snapshot()
        assert snap["daily_spend"] == pytest.approx(8.0)

    def test_record_spend_returns_state(self, guard):
        result = guard.record_spend(7.5)
        assert "daily_spend" in result
        assert result["daily_spend"] == pytest.approx(7.5)

    def test_record_spend_persists_to_disk(self, tmp_path):
        g = CostGuard(state_dir=str(tmp_path / ".state"))
        g.record_spend(12.0)
        # Reload from disk
        g2 = CostGuard(state_dir=str(tmp_path / ".state"))
        snap = g2.snapshot()
        assert snap["daily_spend"] == pytest.approx(12.0)


class TestAlertApproaching:
    def test_no_alert_below_threshold(self, guard):
        guard.record_spend(5.0)  # 20% of 25
        assert guard.alert_approaching() is False

    def test_alert_at_threshold(self, guard):
        guard.record_spend(20.0)  # exactly 80% of 25
        assert guard.alert_approaching() is True

    def test_alert_above_threshold(self, guard):
        guard.record_spend(24.0)  # 96% of 25
        assert guard.alert_approaching() is True


class TestAutoReset:
    def test_reset_after_24h(self, guard):
        guard.record_spend(20.0)
        # Simulate 25 hours having passed since last_reset
        p = guard._load()
        p["last_reset"] = time.time() - 90000  # 25 hours ago
        guard._save(p)
        # After auto-reset, daily_spend should be 0
        snap = guard.snapshot()
        assert snap["daily_spend"] == 0.0

    def test_no_reset_within_24h(self, guard):
        guard.record_spend(15.0)
        snap = guard.snapshot()
        assert snap["daily_spend"] == pytest.approx(15.0)


class TestSnapshot:
    def test_snapshot_keys(self, guard):
        snap = guard.snapshot()
        assert "daily_budget" in snap
        assert "daily_spend" in snap
        assert "last_reset" in snap
        assert "alert" in snap
        assert "remaining" in snap

    def test_snapshot_remaining_calculation(self, guard):
        guard.record_spend(10.0)
        snap = guard.snapshot()
        assert snap["remaining"] == pytest.approx(15.0)

    def test_snapshot_alert_false_initially(self, guard):
        snap = guard.snapshot()
        assert snap["alert"] is False


class TestSetBudget:
    def test_set_budget_changes_limit(self, guard):
        guard.set_budget(50.0)
        snap = guard.snapshot()
        assert snap["daily_budget"] == pytest.approx(50.0)

    def test_set_budget_persists(self, tmp_path):
        g = CostGuard(state_dir=str(tmp_path / ".state"))
        g.set_budget(100.0)
        g2 = CostGuard(state_dir=str(tmp_path / ".state"))
        assert g2.snapshot()["daily_budget"] == pytest.approx(100.0)
