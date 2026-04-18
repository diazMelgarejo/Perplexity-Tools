# 02. Idempotent Installs — Execute Bits, capture_output, Model Discovery

**TL;DR:** `npm install -g` does not guarantee execute bits. `PermissionError ≠ CalledProcessError`. Never hardcode model names — query the backend at runtime.

---

## Root Cause (2026-04-07)

1. **`capture_output=True`** hides all subprocess output — bootstrap appears frozen
2. **`npm install -g` missing execute bit** — binary found by `shutil.which()` but `subprocess.run()` raises `PermissionError: [Errno 13]`
3. **Hardcoded model names** — LM Studio `400`, Ollama `404` when model not loaded

---

## PT-Specific Files

| File | Issue | Fix |
|------|-------|-----|
| `openclaw_bootstrap.py` | `capture_output=True` silenced install output | Removed; output streams to terminal |
| `openclaw_bootstrap.py` | No execute-bit check after `npm install -g openclaw` | Added `chmod +x` if `S_IXUSR` missing |
| `scripts/launch_researchers.py` | Hardcoded model names in researcher config | Added `_resolve_ollama_model()` + `_resolve_lmstudio_model()` |
| `orchestrator/agent_tracker.py` | `AgentRecord(**v)` crash on stale routing data | `_load()` now `isinstance(v, dict)` guards every entry |

---

## Fix

```python
# execute bit check (openclaw_bootstrap.py)
import stat, shutil
from pathlib import Path

path = shutil.which("openclaw")
if path and not (Path(path).stat().st_mode & stat.S_IXUSR):
    Path(path).chmod(Path(path).stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

# exception handling
try:
    subprocess.run(["openclaw", "--version"], check=True)
except subprocess.CalledProcessError as e:
    print(f"openclaw exited with {e.returncode}")
except PermissionError:
    print("Fix: chmod +x $(which openclaw)")

# runtime model discovery (scripts/launch_researchers.py)
def _resolve_ollama_model(host, port, preferred):
    r = httpx.get(f"http://{host}:{port}/api/tags", timeout=5)
    names = [m["name"] for m in r.json().get("models", [])]
    return preferred if preferred in names else (names[0] if names else preferred)
```

---

## Rules

1. **Never use `capture_output=True` in bootstrap subprocess calls**
2. **After any `npm install -g`, verify and fix execute bits**
3. **Catch `PermissionError` separately from `CalledProcessError`**
4. **Never hardcode model names** — query `/v1/models` or `/api/tags` at runtime
5. **`AgentTracker._load()` must `isinstance(v, dict)`** before `**v` unpacking

---

## Commits
- `ffb1be0` (PT) — fix(researchers): auto-discover loaded model via /v1/models + /api/tags
- `d9e4f50` (PT) — fix(tracker): handle stale routing data in agents.json

## Related

- [Session log 2026-04-07](../LESSONS.md#2026-04-07--claude--idempotent-installs-subprocess-permissions--model-auto-discovery)
- [UTS/02](https://github.com/diazMelgarejo/ultrathink-system/blob/main/docs/wiki/02-idempotent-installs.md) — same topic with UTS-specific files
