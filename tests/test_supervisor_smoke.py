"""Mac-only smoke tests for OrchestrationSupervisor V1 (file-based persistence).

Acceptance: ``pytest -k supervisor_smoke`` → green on Mac with no Windows box reachable.
No live LLM calls — echo backend only.  All tests use a tmp_path fixture so the
real .state/ directory is never touched.

Reference: orama-system/docs/2026-05-08-v1-supervisor-brainstorm.md §6 step 6
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from orchestrator.supervisor import (
    JobSpec,
    JobStatus,
    OrchestrationSupervisor,
    _append_event,
    _load_events,
    _latest_status_per_job,
    _new_id,
)


# ── Fixtures / helpers ────────────────────────────────────────────────────────

def _echo_spec(prompt: str = "hello") -> JobSpec:
    return JobSpec(
        job_id=_new_id(),
        intent="echo",
        prompt=prompt,
        backend_hint="echo",
    )


def _make_sup(tmp_path: Path) -> OrchestrationSupervisor:
    return OrchestrationSupervisor(state_dir=tmp_path)


# ── Basic lifecycle ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_submit_echo_job_succeeds(tmp_path):
    """submit_job() fires worker; job reaches SUCCEEDED."""
    sup = _make_sup(tmp_path)
    spec = _echo_spec("hello supervisor")
    job_id = await sup.submit_job(spec)
    assert job_id == spec.job_id

    await asyncio.sleep(0.2)

    status = await sup.get_status(job_id)
    assert status is not None
    assert status["status"] == JobStatus.SUCCEEDED.value


@pytest.mark.asyncio
async def test_artifact_file_written(tmp_path):
    """result.json is written under .state/jobs/<id>/."""
    sup = _make_sup(tmp_path)
    spec = _echo_spec("artifact test")
    job_id = await sup.submit_job(spec)
    await asyncio.sleep(0.2)

    result_path = tmp_path / "jobs" / job_id / "result.json"
    assert result_path.exists(), f"Expected artifact at {result_path}"
    data = json.loads(result_path.read_text())
    assert data["backend"] == "echo"
    assert "artifact test" in data["output"]


@pytest.mark.asyncio
async def test_status_has_artifact_key(tmp_path):
    """get_status() returns artifact path after job succeeds."""
    sup = _make_sup(tmp_path)
    spec = _echo_spec("status artifact")
    job_id = await sup.submit_job(spec)
    await asyncio.sleep(0.2)

    status = await sup.get_status(job_id)
    assert status["artifact"] is not None
    assert "result.json" in status["artifact"]


# ── Event log ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_jobs_jsonl_event_log(tmp_path):
    """All three mandatory transitions appear in jobs.jsonl."""
    sup = _make_sup(tmp_path)
    spec = _echo_spec()
    await sup.submit_job(spec)
    await asyncio.sleep(0.2)

    events = _load_events(tmp_path / "jobs.jsonl")
    job_events = [e for e in events if e.get("job_id") == spec.job_id]
    statuses = {e["status"] for e in job_events}

    assert JobStatus.QUEUED.value in statuses
    assert JobStatus.RUNNING.value in statuses
    assert JobStatus.SUCCEEDED.value in statuses


def test_load_events_missing_file(tmp_path):
    """_load_events() returns [] when jobs.jsonl does not exist."""
    missing = tmp_path / "nonexistent.jsonl"
    assert _load_events(missing) == []


def test_append_event_creates_file(tmp_path):
    """_append_event() creates jobs.jsonl if it does not exist."""
    jobs_file = tmp_path / "jobs.jsonl"
    assert not jobs_file.exists()
    _append_event(jobs_file, "test-id", {"status": "queued"})
    assert jobs_file.exists()
    events = _load_events(jobs_file)
    assert len(events) == 1
    assert events[0]["status"] == "queued"


def test_latest_status_per_job_last_wins(tmp_path):
    """_latest_status_per_job() returns the last event for each job_id."""
    jobs_file = tmp_path / "jobs.jsonl"
    _append_event(jobs_file, "j1", {"status": "queued"})
    _append_event(jobs_file, "j1", {"status": "running"})
    _append_event(jobs_file, "j1", {"status": "succeeded"})
    _append_event(jobs_file, "j2", {"status": "queued"})

    events = _load_events(jobs_file)
    states = _latest_status_per_job(events)
    assert states["j1"]["status"] == "succeeded"
    assert states["j2"]["status"] == "queued"


# ── Guard rails ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_depth_limit_enforced(tmp_path):
    """Jobs with depth > MAX_DEPTH are rejected before worker fires."""
    sup = _make_sup(tmp_path)
    spec = JobSpec(
        job_id=_new_id(),
        intent="echo",
        prompt="nested",
        backend_hint="echo",
        constraints={"depth": 2},
    )
    with pytest.raises(ValueError, match="MAX_DEPTH"):
        await sup.submit_job(spec)


@pytest.mark.asyncio
async def test_cancel_running_job(tmp_path):
    """cancel() returns True and job reaches CANCELLED state."""
    sup = _make_sup(tmp_path)
    spec = _echo_spec("slow")

    async def _slow(s):
        await asyncio.sleep(60)
        return {"output": "never"}

    sup._dispatch = _slow
    job_id = await sup.submit_job(spec)
    await asyncio.sleep(0.05)  # let task start

    cancelled = await sup.cancel(job_id)
    assert cancelled is True
    await asyncio.sleep(0.1)

    status = await sup.get_status(job_id)
    assert status["status"] == JobStatus.CANCELLED.value


# ── Replay ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_replay_creates_new_job(tmp_path):
    """replay() creates a new job_id; new job reaches SUCCEEDED."""
    sup = _make_sup(tmp_path)
    spec = _echo_spec("replay me")
    original_id = await sup.submit_job(spec)
    await asyncio.sleep(0.2)

    # Inject a FAILED event so replay is valid (replay works on any terminal state)
    _append_event(
        tmp_path / "jobs.jsonl",
        original_id,
        {"status": JobStatus.FAILED.value, "spec": spec.to_dict(), "error": "injected"},
    )

    new_id = await sup.replay(original_id)
    assert new_id != original_id
    await asyncio.sleep(0.2)

    new_status = await sup.get_status(new_id)
    assert new_status["status"] == JobStatus.SUCCEEDED.value


@pytest.mark.asyncio
async def test_replay_unknown_job_raises(tmp_path):
    """replay() raises ValueError for an unknown job_id."""
    sup = _make_sup(tmp_path)
    with pytest.raises(ValueError, match="not found"):
        await sup.replay("no-such-id")


# ── list_jobs ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_jobs_filtered_by_status(tmp_path):
    """list_jobs(SUCCEEDED) returns only succeeded jobs."""
    sup = _make_sup(tmp_path)
    s1 = _echo_spec("job one")
    s2 = _echo_spec("job two")
    await sup.submit_job(s1)
    await sup.submit_job(s2)
    await asyncio.sleep(0.3)

    succeeded = sup.list_jobs(status=JobStatus.SUCCEEDED)
    ids = {j["job_id"] for j in succeeded}
    assert s1.job_id in ids
    assert s2.job_id in ids


@pytest.mark.asyncio
async def test_list_jobs_no_filter(tmp_path):
    """list_jobs() with no filter returns all jobs."""
    sup = _make_sup(tmp_path)
    s1 = _echo_spec("a")
    s2 = _echo_spec("b")
    await sup.submit_job(s1)
    await sup.submit_job(s2)
    await asyncio.sleep(0.3)

    all_jobs = sup.list_jobs()
    ids = {j["job_id"] for j in all_jobs}
    assert s1.job_id in ids
    assert s2.job_id in ids
