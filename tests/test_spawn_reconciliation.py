"""Focused tests for SpawnReconciler.reconcile_orphans() null-safety.

Covers the two code paths where tracker.update_status() can return None
(agent disappears between scan and status update — TOCTOU race):
  1. New-spawn branch: update_status returns None → falls back to new_agent
  2. Orphan-resume branch: update_status returns None → endpoint skipped
"""
import asyncio
from unittest.mock import MagicMock, AsyncMock

import pytest

from orchestrator.spawn_reconciliation import SpawnReconciler
from orchestrator.agent_tracker import AgentRecord


def _make_ep(host="10.0.0.1", port=11434, models=None, server_type="ollama"):
    ep = MagicMock()
    ep.host, ep.port = host, port
    ep.models = models or ["qwen3:8b"]
    ep.server_type = server_type
    return ep


def _make_record(agent_id="a1", role="recruited-reasoner", host="10.0.0.1", port=11434, status="starting"):
    return AgentRecord(
        agent_id=agent_id,
        role=role,
        model="qwen3:8b",
        backend="ollama",
        status=status,
        host=host,
        port=port,
        created_at=0.0,
        updated_at=0.0,
    )


def test_new_spawn_handles_update_returning_none():
    """update_status returning None in new-spawn branch must not crash.

    Before fix: update_status return was discarded; new_agent (status='starting')
    was appended regardless.  After fix: falls back to new_agent only when
    update_status returns None, without AttributeError.
    """
    tracker = MagicMock()
    tracker.list_agents.return_value = []
    tracker.register.return_value = _make_record()
    tracker.update_status.return_value = None  # agent disappeared immediately

    discovery = MagicMock()
    discovery.scan_lan = AsyncMock(return_value=[_make_ep()])

    result = asyncio.run(SpawnReconciler(tracker, discovery).reconcile_orphans())
    # Falls back to new_agent — result has one entry, no exception raised
    assert len(result) == 1


def test_orphan_skipped_when_update_returns_none():
    """Orphaned agent that disappears mid-reconcile must be skipped cleanly.

    Before fix: updated.agent_id on line after update_status raised AttributeError
    when update_status returned None.  After fix: `continue` skips the endpoint.
    """
    existing = _make_record(agent_id="a2", role="reasoner",
                            host="10.0.0.2", port=11434, status="starting")
    tracker = MagicMock()
    tracker.list_agents.return_value = [existing]
    tracker.update_status.return_value = None  # agent gone between scan and update

    discovery = MagicMock()
    discovery.scan_lan = AsyncMock(return_value=[_make_ep(host="10.0.0.2", port=11434)])

    result = asyncio.run(SpawnReconciler(tracker, discovery).reconcile_orphans())
    assert result == []  # endpoint skipped, no AttributeError
