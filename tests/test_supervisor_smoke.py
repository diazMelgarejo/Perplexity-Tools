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
    """depth != 0 is rejected at JobSpec construction (V1 invariant: workers never
    spawn sub-workers).  ValidationError or ValueError raised at model creation time,
    NOT at submit_job time — the Pydantic @field_validator catches it first."""
    from pydantic import ValidationError
    with pytest.raises((ValidationError, ValueError)):
        JobSpec(
            job_id=_new_id(),
            intent="echo",
            prompt="nested",
            backend_hint="echo",
            depth=1,  # depth=0 is the only valid value in V1
        )


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


# ── Windows coder pool dispatch ───────────────────────────────────────────────
# _get_reachable_windows_coder is now async (uses httpx.AsyncClient).
# Tests mock the method directly instead of patching the sync connectivity helper.

@pytest.mark.asyncio
async def test_dispatch_prefers_windows_coder_when_reachable(tmp_path, monkeypatch):
    """When a Windows coder endpoint is reachable, _dispatch routes to it before Mac-local."""
    from unittest.mock import AsyncMock
    import orchestrator.worker_registry as reg_mod

    async def fake_win_worker(spec):
        # Verify the dispatcher injects the pre-probed endpoint into metadata.
        assert spec.metadata.get("_win_endpoint") == "http://192.168.254.103:1234"
        return {"backend": "lmstudio-win", "output": "fake win result"}

    monkeypatch.setattr(
        OrchestrationSupervisor,
        "_get_reachable_windows_coder",
        AsyncMock(return_value="http://192.168.254.103:1234"),
    )
    monkeypatch.setitem(reg_mod.WORKER_REGISTRY, "lmstudio-win", fake_win_worker)

    sup = _make_sup(tmp_path)
    spec = JobSpec(
        job_id=_new_id(),
        intent="code review",
        prompt="review this file",
        backend_hint="lmstudio-mac",
    )
    result = await sup._dispatch(spec)
    assert result.get("routed_to_windows") is True, (
        f"Expected Windows coder routing but got: {result}"
    )
    assert result.get("windows_endpoint") == "http://192.168.254.103:1234"


@pytest.mark.asyncio
async def test_dispatch_skips_windows_coder_when_unreachable(tmp_path, monkeypatch):
    """When Windows coder is unreachable, _dispatch falls through to normal routing."""
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        OrchestrationSupervisor,
        "_get_reachable_windows_coder",
        AsyncMock(return_value=None),
    )

    sup = _make_sup(tmp_path)
    spec = _echo_spec("fallthrough test")
    result = await sup._dispatch(spec)
    assert result.get("routed_to_windows") is not True
    assert "echo" in str(result).lower() or result.get("status") == "ok"


@pytest.mark.asyncio
async def test_dispatch_skips_windows_coder_when_pool_empty(tmp_path, monkeypatch):
    """When WIN_CODER_ENDPOINTS is empty, _get_reachable_windows_coder returns None."""
    monkeypatch.setenv("WIN_CODER_ENDPOINTS", "")

    sup = _make_sup(tmp_path)
    # Call the method directly to confirm it returns None for empty pool.
    result = await OrchestrationSupervisor._get_reachable_windows_coder()
    assert result is None

    # Also confirm _dispatch falls through to normal routing.
    spec = _echo_spec("empty pool test")
    dispatch_result = await sup._dispatch(spec)
    assert dispatch_result.get("routed_to_windows") is not True


# ── _try_skill_envelope dispatch gate ─────────────────────────────────────────

def test_try_skill_envelope_raises_for_missing_skill_tree():
    """Mapped task_type with missing openclaw-skills tree raises RuntimeError (fail-closed).

    _DEFAULT_OPENCLAW_SKILLS_ROOT is computed at module import time, so patching
    ORAMA_SYSTEM_ROOT after import has no effect.  Instead we patch
    _find_skills_root directly to raise SkillResolutionError as it would on a
    fresh machine where the submodule is not yet checked out.
    """
    from unittest.mock import patch
    from orchestrator.openclaw_skill_resolver import SkillResolutionError
    spec = JobSpec(
        job_id=_new_id(),
        intent="add channel",
        prompt="add webhook",
        backend_hint="echo",
        task_type="add_channel",
    )

    def _raise_resolution_error():
        raise SkillResolutionError(
            "openclaw-skills folder not found (injected for test)"
        )

    with patch(
        "orchestrator.openclaw_skill_resolver._find_skills_root",
        side_effect=_raise_resolution_error,
    ):
        with pytest.raises(RuntimeError, match="Skill routing failed"):
            OrchestrationSupervisor._try_skill_envelope(spec)


def test_get_constraint_safe_with_list_constraints():
    """_get_constraint must not raise AttributeError when constraints is a list of tags."""
    from orchestrator.worker_registry import _get_constraint

    class _FakeSpec:
        constraints = ["gpu-required", "no-streaming"]

    assert _get_constraint(_FakeSpec(), "max_seconds", 300) == 300
    assert _get_constraint(_FakeSpec(), "max_tokens", 4096) == 4096
    assert _get_constraint(_FakeSpec(), "any_key", "default_val") == "default_val"


def test_get_constraint_reads_dict_constraints():
    """_get_constraint returns the keyed value when constraints is a dict."""
    from orchestrator.worker_registry import _get_constraint

    class _FakeSpec:
        constraints = {"max_seconds": 600, "max_tokens": 8192}

    assert _get_constraint(_FakeSpec(), "max_seconds", 300) == 600
    assert _get_constraint(_FakeSpec(), "max_tokens", 4096) == 8192
    assert _get_constraint(_FakeSpec(), "missing_key", "fallback") == "fallback"


def test_try_skill_envelope_returns_none_for_unknown_task_type():
    """_try_skill_envelope returns None for task_types not in the skill map."""
    spec = JobSpec(
        job_id=_new_id(),
        intent="general coding",
        prompt="write a function",
        backend_hint="echo",
        task_type="general",
    )
    result = OrchestrationSupervisor._try_skill_envelope(spec)
    assert result is None


def test_try_skill_envelope_returns_none_when_no_task_type():
    """_try_skill_envelope returns None gracefully when task_type is empty."""
    spec = JobSpec(
        job_id=_new_id(),
        intent="echo",
        prompt="hello",
        backend_hint="echo",
    )
    result = OrchestrationSupervisor._try_skill_envelope(spec)
    assert result is None


# ── replay() preserves task_type ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_replay_preserves_task_type(tmp_path):
    """replay() must carry task_type forward so retried skill-mapped jobs route correctly."""
    sup = _make_sup(tmp_path)
    spec = JobSpec(
        job_id=_new_id(),
        intent="add channel",
        prompt="add a webhook channel",
        backend_hint="echo",
        task_type="add_channel",
    )
    original_id = spec.job_id

    # Inject a FAILED event so replay() has something to replay.
    _append_event(
        tmp_path / "jobs.jsonl",
        original_id,
        {
            "status": JobStatus.FAILED.value,
            "spec": spec.model_dump(),
            "error": "injected failure",
        },
    )

    new_id = await sup.replay(original_id)
    assert new_id != original_id

    # Load the replayed job's spec from the event log and assert task_type survived.
    events = _load_events(tmp_path / "jobs.jsonl")
    states = _latest_status_per_job(events)
    replayed_state = states.get(new_id) or {}
    replayed_spec = replayed_state.get("spec", {})
    assert replayed_spec.get("task_type") == "add_channel", (
        f"task_type was lost during replay; got: {replayed_spec.get('task_type')!r}"
    )


# ── SkillEnvelope.to_dict() ───────────────────────────────────────────────────

def test_skill_envelope_to_dict_is_json_serialisable():
    """SkillEnvelope.to_dict() must return plain JSON-serialisable types (no Path objects)."""
    import json
    from pathlib import Path as P
    from orchestrator.openclaw_skill_resolver import SkillEnvelope

    envelope = SkillEnvelope(
        skill_id="openclaw-status",
        skill_path=P("/some/path/SKILL.md"),
        args={"key": "value"},
        agent_id="test-agent",
        openclaw_home=P("/home/openclaw"),
        parent_chain=["openclaw-new-agent"],
    )
    d = envelope.to_dict()
    # Must not raise — all values must be JSON-serialisable.
    serialised = json.dumps(d)
    parsed = json.loads(serialised)
    assert parsed["skill_id"] == "openclaw-status"
    assert parsed["skill_path"] == "/some/path/SKILL.md"
    assert parsed["openclaw_home"] == "/home/openclaw"
    assert parsed["depth"] == 1
