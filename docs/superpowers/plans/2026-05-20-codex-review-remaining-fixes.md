# Perpetua-Tools — Remaining Codex Review Fixes

> **Status:** Plan-only. Do NOT execute until user approves.
> **Branch:** `feat/openclaw-skills-spawn-helper` (Perpetua-Tools PR #26)
> **Baseline:** `56b6c8f` — CI green (2 matrix jobs passed at run `26157603064`)

---

## State Audit (as of 2026-05-20)

### Already fixed (committed, CI green)

| # | Codex item | Fixed in |
|---|-----------|---------|
| P1 | `model_dump()` on `@dataclass` SkillEnvelope | `bb016b6` |
| P1 | Probed endpoint not passed to worker | `bb016b6` |
| P1 | Sync `check_lm_studio()` blocking async dispatch | `bb016b6` |
| P2 | `task_type` dropped in `replay()` | `bb016b6` |
| P1 | Backend routing bypassed — any job hijacked by Windows | `56b6c8f` |
| P2 | Worker probe accepts 4xx (`< 500`) | `56b6c8f` |
| P1 | `RecursionBudgetExceeded` swallowed in `_try_skill_envelope` | `56b6c8f` |

### Still open

| # | Priority | Description | File:line |
|---|---------|-------------|-----------|
| A | **P1** | `_try_skill_envelope` swallows `SkillResolutionError` for KNOWN task types | `supervisor.py` ~L394 |
| B | **P1** | `test_returns_correct_shape` brittle — relies on httpx mock for probe; inject `_win_endpoint` instead | `tests/test_lmstudio_win.py` ~L125 |
| C | **P2** | `constraints: Union[List, Dict]` — all workers call `.get()` on it; `AttributeError` when a list | `worker_registry.py` L129, L161–162, L191, L233, L292–293 |
| D | **P2** | `_MAC_LOCAL_BACKENDS` missing `"mlx"` — future MLX worker won't be preempted by Windows coder | `supervisor.py` ~L353 |
| E | **P3** | `resolve_backend` docstring says backend_hint is priority 3 but code checks it first | `worker_registry.py` L76–82 |
| F | **P3** | Item "0 — pass `verbose: true` in second argument to `fetch()`" — need to locate the call site | unknown |

---

## Task A — Fail-closed skill routing (P1)

**Root cause:** `_try_skill_envelope` currently:
```python
except RecursionBudgetExceeded:
    raise
except Exception:
    return None   # ← swallows SkillResolutionError for KNOWN task types
```
When `task_type="status"` but `openclaw-skills/` tree is missing or `SKILL.md`
doesn't exist, the job silently falls through to `ollama` instead of failing.
This violates the deterministic-routing invariant: a mapped `task_type` must
either route to its skill or FAIL — never silently degrade.

**Fix in `orchestrator/supervisor.py`:**
```python
@staticmethod
def _try_skill_envelope(spec: "JobSpec"):
    from orchestrator.openclaw_skill_resolver import (
        RecursionBudgetExceeded,
        SkillResolutionError,
        resolve_skill,
    )
    _SKILL_MAP = { ... }  # unchanged
    task_type = getattr(spec, "task_type", None) or ""
    skill_id = _SKILL_MAP.get(task_type)
    if not skill_id:
        return None   # unmapped task_type → normal routing (correct)
    # task_type IS mapped → fail-closed: any resolver error surfaces as failure
    try:
        args = getattr(spec, "metadata", {}) or {}
        return resolve_skill(skill_id, args, agent_id=spec.job_id)
    except RecursionBudgetExceeded:
        raise   # safety invariant — re-raise, job marked FAILED
    except SkillResolutionError as exc:
        raise RuntimeError(
            f"Skill routing failed for task_type={task_type!r} "
            f"(skill_id={skill_id!r}): {exc}"
        ) from exc
    # Do NOT catch generic Exception — unmapped bugs should surface, not hide
```

**New test in `tests/test_supervisor_smoke.py`:**
```python
def test_try_skill_envelope_raises_for_missing_skill_tree():
    """Mapped task_type with missing openclaw-skills tree raises RuntimeError (fail-closed)."""
    import os
    spec = JobSpec(
        job_id=_new_id(),
        intent="add channel",
        prompt="add webhook",
        backend_hint="echo",
        task_type="add_channel",
    )
    # ORAMA_SYSTEM_ROOT points at a nonexistent path so _find_skills_root() raises
    with patch.dict(os.environ, {"ORAMA_SYSTEM_ROOT": "/nonexistent/path"}):
        with pytest.raises(RuntimeError, match="Skill routing failed"):
            OrchestrationSupervisor._try_skill_envelope(spec)
```

---

## Task B — Robust `test_returns_correct_shape` (P1)

**Root cause:** CI run `26155185362` failed because that job ran on commit `60586b5`
which didn't yet have `.get()` on `_FakeClient`. The latest CI (`26157603064`) passes
because `56b6c8f` (modified by linter) added the `.get()` fix. BUT the test is still
fragile: patching `httpx.AsyncClient` with a single `return_value` instance means BOTH
the probe client and the request client share the same mock. A future refactor that
changes how many clients are created will silently break this test.

**Fix in `tests/test_lmstudio_win.py`:** Replace the test with two variants:

```python
@pytest.mark.asyncio
async def test_returns_correct_shape_with_preprobed_endpoint(self):
    """When _win_endpoint is injected (supervisor dispatch path), no probe is needed."""
    from orchestrator.worker_registry import _lmstudio_win_worker
    spec = self._make_spec(
        # Inject the pre-probed endpoint — bypasses the probe block entirely
        metadata={
            "model": "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2",
            "_win_endpoint": "http://192.168.254.102:1234",
        },
        prompt="Hello",
    )
    fake_resp_data = {
        "choices": [{"message": {"content": "Hi there"}}],
        "usage": {"completion_tokens": 3},
    }

    class _FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return fake_resp_data

    class _FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, **kw): return _FakeResp()
        # No .get() needed — pre-probed path skips the probe entirely

    with patch("httpx.AsyncClient", return_value=_FakeClient()):
        result = await _lmstudio_win_worker(spec)

    assert result["backend"] == "lmstudio-win"
    assert result["output"] == "Hi there"
    assert result["tokens"] == 3
    assert "model" in result

@pytest.mark.asyncio
async def test_returns_correct_shape_direct_call_path(self):
    """When called directly (no _win_endpoint), worker probes then POSTs."""
    from orchestrator.worker_registry import _lmstudio_win_worker
    spec = self._make_spec(
        metadata={"model": "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2"},
        prompt="Hello",
    )
    fake_resp_data = {
        "choices": [{"message": {"content": "Direct result"}}],
        "usage": {"completion_tokens": 5},
    }

    class _FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return fake_resp_data

    class _FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw): return _FakeResp()   # probe
        async def post(self, url, **kw): return _FakeResp()  # request

    with patch.dict(os.environ, {"LM_STUDIO_WIN_ENDPOINTS": "http://192.168.254.102:1234"}):
        with patch("httpx.AsyncClient", return_value=_FakeClient()):
            result = await _lmstudio_win_worker(spec)

    assert result["backend"] == "lmstudio-win"
    assert result["output"] == "Direct result"
    assert result["tokens"] == 5
```

Remove the original `test_returns_correct_shape` entirely (replaced by the two above).

---

## Task C — Fix `constraints` list/dict hazard (P2)

**Root cause:** `JobSpec.constraints` is typed as `Union[List[str], Dict[str, Any]]`
(list = constraint tags, dict = key-value like `max_seconds`/`max_tokens`). Every worker
does `.get("max_seconds", 300)` directly, which raises `AttributeError` when constraints
is a list.

**Fix in `orchestrator/worker_registry.py` — add helper at module top:**
```python
def _get_constraint(spec: Any, key: str, default: Any = None) -> Any:
    """Return spec.constraints[key] safely for both dict and list constraint shapes.

    dict constraints → key-value lookup (e.g. max_seconds=300)
    list constraints → tag-only; always returns default for key lookups
    """
    constraints = getattr(spec, "constraints", None) or {}
    if isinstance(constraints, dict):
        return constraints.get(key, default)
    return default  # list = tags only, no key-value pairs
```

**Replace all 5 call sites:**
```python
# Before (fragile):
timeout = float(getattr(spec, "constraints", {}).get("max_seconds", 120))
# After (safe):
timeout = float(_get_constraint(spec, "max_seconds", 120))
```

Affected workers: `_ollama_mac_worker`, `_lmstudio_mac_worker`, `_ollama_worker`,
`_codex_worker`, `_lmstudio_win_worker`. Also affects `_gemini_worker` if it reads constraints.

**New test in `tests/test_backend_routing.py` or `tests/test_supervisor_smoke.py`:**
```python
def test_lmstudio_win_worker_handles_list_constraints():
    """Worker must not crash when constraints is a list of tags (not a dict)."""
    from orchestrator.worker_registry import _get_constraint
    class FakeSpec:
        constraints = ["gpu-required", "no-streaming"]
    assert _get_constraint(FakeSpec(), "max_seconds", 300) == 300
    assert _get_constraint(FakeSpec(), "max_tokens", 4096) == 4096
```

---

## Task D — Add `"mlx"` to `_MAC_LOCAL_BACKENDS` (P2)

**Root cause:** `_MAC_LOCAL_BACKENDS = {"ollama", "ollama-mac", "lmstudio-mac"}` in
`_dispatch()`. If an `mlx` worker is added (it's in `WORKER_REGISTRY` placeholder in
`ROLE_BACKEND_MAP` vicinity), those jobs won't be preempted by the Windows coder.

**Fix in `orchestrator/supervisor.py`:**
```python
# In _dispatch(), replace:
_MAC_LOCAL_BACKENDS = {"ollama", "ollama-mac", "lmstudio-mac"}
# With:
_MAC_LOCAL_BACKENDS = {"ollama", "ollama-mac", "lmstudio-mac", "mlx"}
```

Also extract as a module-level constant so it's not hidden inside a method:
```python
# At module top, after imports:
_MAC_LOCAL_BACKENDS: frozenset[str] = frozenset(
    {"ollama", "ollama-mac", "lmstudio-mac", "mlx"}
)
```

---

## Task E — Fix `resolve_backend` docstring (P3)

**Root cause:** The docstring lists priority order as `1. role/spec, 2. intent, 3. backend_hint`
but the code checks `backend_hint` FIRST (lines 84–86), making it the highest-priority
override. The comment is misleading to anyone reading the routing logic.

**Fix in `orchestrator/worker_registry.py`:**
```python
def resolve_backend(spec: Any) -> str:
    """Resolve backend using priority order from § 5.2.

    1. backend_hint — explicit override (highest priority when non-empty/non-auto)
    2. role + specialization → ROLE_BACKEND_MAP
    3. intent → _INTENT_BACKEND_MAP
    """
```

---

## Task F — Locate "verbose: true in fetch()" (P3)

**Status:** Unknown call site. Cannot find `fetch()` in:
- `packages/` (directory empty or no JS)
- `orama-system/bin/` scripts
- `orchestrator/` Python modules

**Hypothesis:** This comment is from a Codex review on orama-system PR #34 (the
submodule bootstrap fix), not PR #26. The `git submodule update --init --recursive`
line in `start.sh` should add `--progress` to prevent silent hangs in CI:
```bash
# Before:
git submodule update --init --recursive
# After:
git submodule update --init --recursive --progress
```

**Action needed:** Check orama-system PR #34 inline comments for the exact call site.
If it IS in a JS `fetch()` call, locate the file and add `verbose: true` to options.

---

## Execution Order

```
Task F (locate) → clarify with user if needed
Task A (fail-closed skill routing) → 1 file + 1 test
Task B (robust test_returns_correct_shape) → 1 test file change
Task C (_get_constraint helper) → 1 file + 1 test
Task D (mlx in MAC_LOCAL) → 1 line in supervisor.py
Task E (docstring) → 1 line fix
→ Run full test suite
→ Single commit: "fix(dispatch+routing): remaining Codex review items"
→ Push to feat/openclaw-skills-spawn-helper
```

---

## Verification Checklist

After execution:
```bash
# All tests must pass
pytest tests/test_supervisor_smoke.py tests/test_lmstudio_win.py -v

# Full suite
pytest tests/ -v --tb=short

# Confirm no new Codex review items remain open
gh api repos/diazMelgarejo/Perpetua-Tools/pulls/26/comments --jq '.[].body'
```

Expected: all Codex P1/P2 items addressed, CI green on push.
