# 06. Startup & IP Detection — stdin Deadlock, load_dotenv, Concurrent Probing

**TL;DR:** `input()` in a daemon thread causes Abort trap: 6 at Python shutdown. Always `load_dotenv()` explicitly. Fire all backend probes with `asyncio.create_task()` concurrently.

---

## Root Cause (2026-04-13)

Three separate failures on first `./start.sh` run:

1. **Abort trap: 6** — `_gather_alphaclaw_credentials()` spawned a daemon thread calling `input()`. After `t.join(30)` timeout, thread held the stdin `BufferedReader` lock → Python shutdown SIGABRT.

2. **Silent IP misconfiguration** — `agent_launcher.py` read env vars but `load_dotenv()` was never called → hard-coded fallbacks (`.103`, `.100`) always used instead of `.110` / `.108`.

3. **Sequential backend probes** — probing 4 backends one-at-a-time added 2–5s wall-clock on every startup.

---

## PT-Specific Files

| File | Issue | Fix |
|------|-------|-----|
| `orchestrator.py` / `start.sh` | `input()` in daemon thread → SIGABRT | `sys.stdin.isatty()` guard + `</dev/null` in start.sh |
| `alphaclaw_bootstrap.py` | Gateway `Popen` inherited broken stdin fd | `stdin=subprocess.DEVNULL` on gateway Popen |
| `agent_launcher.py` | `load_dotenv()` never called | Added at module level before any env reads |
| `agent_launcher.py` | Sequential probe order | `asyncio.create_task()` for all 4 probes at t=0 |
| `agent_launcher.py` | Stale IPs persist across restarts | `_persist_detected_ips()` writes back confirmed URLs to `.env` |

---

## Fix

```python
# agent_launcher.py — at module level (MUST be before any os.getenv calls)
from dotenv import load_dotenv
load_dotenv(".env")
load_dotenv(".env.local", override=True)

# stdin guard for any thread that calls input()
if sys.stdin.isatty():
    t = threading.Thread(target=_gather_credentials, daemon=True)
    t.start()
    t.join(30)

# concurrent probing
async def probe_all():
    tasks = [
        asyncio.create_task(_probe_ollama(LOCAL_URL)),
        asyncio.create_task(_probe_lmstudio(LOCAL_LMS_URL)),
        asyncio.create_task(_probe_ollama(WIN_URL)),
        asyncio.create_task(_probe_lmstudio(WIN_LMS_URL)),
    ]
    local_ok, local_lms_ok, win_ok, win_lms_ok = await asyncio.gather(*tasks)
    return local_ok, local_lms_ok, win_ok, win_lms_ok
```

```bash
# start.sh — redirect stdin for all Python orchestrator processes
python "$SCRIPT_DIR/orchestrator.py" </dev/null
```

---

## Rules

1. **Never call `input()` in a daemon thread** — `sys.stdin.isatty()` guard required
2. **`python script.py </dev/null`** for all long-running orchestrator processes in start.sh
3. **`stdin=subprocess.DEVNULL`** on any gateway `Popen`
4. **`load_dotenv()` at module level** in every Python entry point — shell vars alone are unreliable
5. **Fire all backend probes concurrently** — `asyncio.create_task()` at t=0
6. **`_persist_detected_ips()`** after probes — config is self-correcting

---

## Related

- [Session log 2026-04-13](../LESSONS.md#2026-04-13--claude--startup-fix-ip-detection-stdin-deadlock-concurrent-backend-probing)
- [UTS/07](https://github.com/diazMelgarejo/ultrathink-system/blob/main/docs/wiki/07-startup-ip-detection.md) — full code samples
