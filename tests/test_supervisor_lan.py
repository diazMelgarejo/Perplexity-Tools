"""LAN integration tests for OrchestrationSupervisor — DEFERRED.

These tests require both Mac AND Windows nodes to be LAN-live simultaneously.
They are skipped automatically when the Win node is unreachable.

Run when both nodes are up:
    pytest -k supervisor_lan -v

Deferred because (as of 2026-05-08): Win+Mac simultaneous session not yet verified.
See: orama-system/docs/2026-05-08-v1-supervisor-brainstorm.md §9 (deferred list)
"""
from __future__ import annotations

import os
import socket
import pytest

from orchestrator.supervisor import JobSpec, JobStatus, OrchestrationSupervisor, _new_id


# ── Skip guard ────────────────────────────────────────────────────────────────
_WIN_IP = os.getenv("WIN_IP", "192.168.254.108")
_WIN_PORT = int(os.getenv("WIN_LMS_PORT", "1234"))


def _both_nodes_up() -> bool:
    """Return True only when the Windows LM Studio node is reachable on LAN."""
    try:
        s = socket.create_connection((_WIN_IP, _WIN_PORT), timeout=2)
        s.close()
        return True
    except OSError:
        return False


_skip_unless_lan = pytest.mark.skipif(
    not _both_nodes_up(),
    reason=f"Windows node {_WIN_IP}:{_WIN_PORT} not reachable — LAN tests deferred",
)


# ── LAN tests ─────────────────────────────────────────────────────────────────

@_skip_unless_lan
@pytest.mark.asyncio
async def test_winonly_model_routes_to_win(tmp_path):
    """Submit a Windows-only model job from Mac; assert routing lands on Win node.

    Verifies: intent-routed dispatch picks lmstudio-win backend when the
    submitted model is listed as windows_only in model_hardware_policy.yml.
    """
    sup = OrchestrationSupervisor(state_dir=tmp_path)
    spec = JobSpec(
        job_id=_new_id(),
        intent="debug",
        prompt="print('hello from win')",
        backend_hint="lmstudio-win",
        metadata={"model": "deepseek-r1:14b"},  # windows_only model
    )
    job_id = await sup.submit_job(spec)
    import asyncio
    await asyncio.sleep(5)

    status = await sup.get_status(job_id)
    assert status is not None
    result = status.get("result") or {}
    assert result.get("backend") == "lmstudio-win", (
        f"Expected lmstudio-win backend, got: {result.get('backend')}"
    )


@_skip_unless_lan
@pytest.mark.asyncio
async def test_failclosed_when_win_offline(tmp_path):
    """Win node down + Win-only model requested → JobStatus.FAILED with policy=True.

    To run this test: temporarily bring down the Win node while keeping the
    test invoked.  Or set WIN_IP to an unreachable address before running.
    """
    import os
    # Force an unreachable Win IP for this test
    original = os.getenv("WIN_IP")
    os.environ["WIN_IP"] = "192.168.254.250"  # guaranteed unreachable

    sup = OrchestrationSupervisor(state_dir=tmp_path)
    spec = JobSpec(
        job_id=_new_id(),
        intent="debug",
        prompt="test fail-closed",
        backend_hint="lmstudio-win",
        constraints={"max_seconds": 5},
    )

    try:
        job_id = await sup.submit_job(spec)
        import asyncio
        await asyncio.sleep(6)

        status = await sup.get_status(job_id)
        assert status["status"] == JobStatus.FAILED.value, (
            f"Expected FAILED, got {status['status']}"
        )
        # No silent degradation — recovery hint present
        assert status.get("error") is not None
    finally:
        if original is not None:
            os.environ["WIN_IP"] = original
        else:
            os.environ.pop("WIN_IP", None)
