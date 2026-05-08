---
name: startup-intelligence
description: >
  Startup scenario classification, probe retry, history-driven adaptive timeouts,
  cloud fallback, and .env.local override detection for Perpetua-Tools and orama-system.
  Use when startup fails to reach backends, when you need to understand which scenario
  the system is in (FULL_DISTRIBUTED, MAC_DUAL, MAC_OLLAMA_ONLY, MAC_LMS_ONLY,
  CLOUD_ONLY, FULLY_OFFLINE), or when routing behaves unexpectedly after reboot.
---

# Startup Intelligence — Skill

## Purpose

This skill encodes everything needed to diagnose, extend, or replicate the startup
scenario engine introduced in Perpetua-Tools v0.9.9.8.  It is the canonical reference
for agents working on `agent_launcher.py`, `start.sh`, or any code that probes LAN
backends at startup.

---

## 1. The Six Scenarios

Every startup run maps to exactly one `StartupScenario`:

| Scenario | Condition | Coder backends (priority order) | Manager backends |
|---|---|---|---|
| `FULL_DISTRIBUTED` | mac_any **and** win_any | win-lmstudio, win-ollama, mac-ollama, mac-lmstudio | mac-ollama, mac-lmstudio |
| `MAC_DUAL` | mac_ok **and** mac_lms_ok (no win) | mac-ollama, mac-lmstudio | mac-ollama, mac-lmstudio |
| `MAC_OLLAMA_ONLY` | mac_ok only | mac-ollama | mac-ollama |
| `MAC_LMS_ONLY` | mac_lms_ok only | mac-lmstudio | mac-lmstudio |
| `CLOUD_ONLY` | no local backends; cloud API key present | cloud-api | cloud-api |
| `FULLY_OFFLINE` | nothing reachable | (empty) | (empty) |

**Classification rule** (first match wins):

```python
mac_any = mac_ok or mac_lms_ok
win_any = win_ok or lms_ok   # lms_ok = Windows LM Studio

if mac_any and win_any:      return FULL_DISTRIBUTED
if mac_ok and mac_lms_ok:    return MAC_DUAL
if mac_ok:                   return MAC_OLLAMA_ONLY
if mac_lms_ok:               return MAC_LMS_ONLY
if cloud_ok:                 return CLOUD_ONLY
return FULLY_OFFLINE
```

> **Win-without-Mac is not a valid manager scenario.**  A Windows Ollama/LMS result
> alone falls through to `CLOUD_ONLY` or `FULLY_OFFLINE`.  This is intentional: the
> Mac is the primary coordinator; Windows is a coder-tier worker.

---

## 2. Probe Retry Protocol

Both probe functions (`check_remote_worker`, `check_lmstudio_worker`) now return
`tuple[bool, int | None]` — `(reachable, latency_ms)`.

```python
async def check_remote_worker(
    base_url: str, timeout: int = DETECT_TIMEOUT, _retries: int = 1
) -> tuple[bool, int | None]:
    # Try once.  On failure, sleep 2 s and try once more (_retries controls this).
    # Returns (True, latency_ms) on success, (False, None) after all retries fail.
```

**Rules:**
- Default retry count is **1** (one initial attempt + one retry = 2 total attempts).
- Sleep between retries is fixed at **2 s** — long enough for a backend that is still
  booting, short enough not to block `start.sh` perceptibly.
- Never raise; always return `(False, None)` on final failure.
- Latency is measured as wall-clock ms from request start to first response byte.

**When to increase retries:**  Only do this for the Windows LMS probe if `win_lms_p50`
from history is > 5000 ms — it may simply be slow to accept connections.  Do not
increase Mac probe retries; local sockets fail fast when the service is down.

---

## 3. Startup History

**File:** `.state/startup_history.jsonl`  (relative to the PT repo root)
**Format:** one JSON object per line, newest at the bottom, rolling max 10 entries.

### Schema

```jsonc
{
  "ts":               "2026-05-07T09:14:33",   // ISO-8601, local time
  "scenario":         "FULL_DISTRIBUTED",       // StartupScenario.value
  "win_ip":           "192.168.1.108",          // last detected Windows IP (or null)
  "mac_ol_latency_ms": 12,                      // Mac Ollama probe latency (or null)
  "win_lms_latency_ms": 480                     // Windows LM Studio probe latency (or null)
}
```

All latency fields are optional; agents must tolerate `null` and missing keys.

### Reading history for adaptive hints

```python
from orchestrator.startup_intelligence import build_routing_hints
hints = build_routing_hints(history_list)   # list loaded from JSONL
# hints = {
#   "win_ip_hint":               str | None,   # most recent successful win_ip
#   "win_lms_p50_ms":            int | None,   # P50 latency over last 5 runs
#   "mac_ol_p50_ms":             int | None,
#   "suggested_timeout_win_lms": int,          # 6 if p50 > 2000ms, else 3
#   "suggested_timeout_mac_ol":  int,          # always 3
# }
```

**Minimum samples for P50:** 2.  With only 1 sample, `*_p50_ms` is `None` and the
safe default timeout (3 s) is returned.

### Maintenance

- `_load_history()` reads the file; returns `[]` on missing/corrupt file.
- `_record_startup()` appends one entry and truncates to the last 10 lines atomically.
- The file is ignored by git (add `.state/` to `.gitignore` if not already present).

---

## 4. Adaptive Timeout Logic

Win LMS is the only probe that gets an adaptive timeout.  Mac probes are local sockets
and always use the hard default (3 s).

```
if win_lms_p50_ms is None:   use 3 s   (not enough history)
elif win_lms_p50_ms > 2000:  use 6 s   (slow LAN or heavy model load)
else:                         use 3 s
```

This is surfaced at startup:

```
[agent_launcher] ⏱  win_lms adaptive timeout: 6 s (p50=2842 ms over last 5 runs)
```

---

## 5. Cloud Fallback

Cloud fallback activates when **all local backends are unreachable** AND a valid API
key is present.

### Trigger condition

```python
if coder_backend == "mac-degraded":   # all local coder paths failed
    perplexity_key = os.getenv("PERPLEXITY_API_KEY", "")
    anthropic_key  = os.getenv("ANTHROPIC_API_KEY", "")
    if perplexity_key and not perplexity_key.startswith("your_"):
        coder_endpoint = "https://api.perplexity.ai"
        coder_model    = os.getenv("CLOUD_CODER_MODEL", "sonar-reasoning-pro")
        coder_backend  = "perplexity"
        coder_platform = "cloud"
    elif anthropic_key:
        coder_endpoint = "https://api.anthropic.com"
        coder_model    = os.getenv("CLOUD_CODER_MODEL", "claude-4-5-thinking")
        coder_backend  = "anthropic"
        coder_platform = "cloud"
```

### Affinity check bypass

The hardware affinity check (`check_affinity`) is **skipped** when
`coder_platform == "cloud"`.  Cloud APIs have no hardware affinity constraints.

### Routing state fields

When cloud fallback activates, the routing state dict contains:

```python
{
  "coder_backend":  "perplexity" | "anthropic",
  "coder_platform": "cloud",
  "coder_endpoint": "https://...",
  "coder_model":    "sonar-reasoning-pro" | "claude-4-5-thinking",
  "scenario_name":  "CLOUD_ONLY",
}
```

### Env vars

| Variable | Purpose | Default |
|---|---|---|
| `PERPLEXITY_API_KEY` | Perplexity API key (preferred cloud coder) | — |
| `ANTHROPIC_API_KEY` | Anthropic API key (secondary cloud coder) | — |
| `CLOUD_CODER_MODEL` | Override the default cloud model | `sonar-reasoning-pro` |

---

## 6. `.env.local` Override Bug & Fix

**Bug:** `.env.local` is loaded with `python-dotenv override=True`, so a stale
`WINDOWS_IP=` value there silently wins over a correct value in `.env`.

**Fix:** `_persist_detected_ips()` now patches **both** `.env` and `.env.local`
(when both exist) with the freshly detected IPs, so they stay in sync.

**Diagnostic:** if Windows routing breaks after a DHCP reassignment, check:

```bash
grep WINDOWS_IP .env .env.local   # both should show the same IP
```

---

## 7. orama-system `start.sh` Integration

### Warm-cache fallback

When `alphaclaw_manager --resolve` fails, `start.sh` reads
`.state/routing.json` (the last known good routing state written by PT) and
re-exports:

```bash
PT_MODE=cached
PT_DISTRIBUTED=...
PT_ALPHACLAW_PORT=...
WIN_IP=...
PT_SCENARIO=...
PT_MODE_SOURCE=cache
PT_AGENTS_STATE=<path to routing.json>
```

This ensures services that read env vars at boot don't start with empty endpoints.
**Stale data warning is always printed** so operators know the cache is in use.

### Parallel banner probes

`_print_banner()` runs the three `nc -z -w 1` reachability checks in parallel
background subshells (writing to mktemp files) and `wait`s for all three.
Total banner delay is `max(1 s)` instead of the previous `3 s` worst case.

---

## 8. Diagnostic Patterns

### "Why is the scenario wrong?"

1. Check which probes returned `True`:
   ```
   grep "scenario:" .state/startup_history.jsonl | tail -5
   ```
2. If scenario is `FULLY_OFFLINE` but backends are running, the probe may have
   timed out before they finished booting.  Wait 30 s and re-run.
3. If scenario is `MAC_OLLAMA_ONLY` but LM Studio is running, check that LM Studio
   is listening on port 1234 (default) and that `MAC_LMS_URL` in `.env` matches.

### "Why is Windows being skipped?"

Win-without-Mac is intentional (`FULLY_OFFLINE`, not `WIN_ONLY`).  If you want
Windows coder in a Mac-down scenario, you must start at least one Mac backend first
or route manually via `WIN_LM_STUDIO_HOST` env var.

### "Cloud fallback never activates"

1. Confirm the key is set and non-placeholder:
   ```bash
   python3 -c "import os; print(repr(os.getenv('PERPLEXITY_API_KEY', '')))"
   ```
2. Confirm all local probes actually fail (check the `[agent_launcher]` log lines).
3. `coder_backend` must reach `"mac-degraded"` — if any local backend succeeds,
   cloud is not engaged.

### "Adaptive timeout is stuck at 3 s"

Only 1 history entry → P50 is `None` → safe default 3 s.  Run at least 2 startups
and the adaptive path will engage.

---

## 9. Key Files

| File | Repo | Purpose |
|---|---|---|
| `orchestrator/startup_intelligence.py` | Perpetua-Tools | Scenario engine — zero I/O, pure functions |
| `agent_launcher.py` | Perpetua-Tools | Probe + classify + record + route |
| `tests/test_startup_intelligence.py` | Perpetua-Tools | 20 offline unit tests |
| `tests/test_hardware_routing.py` | Perpetua-Tools | Hardware routing integration tests |
| `.state/startup_history.jsonl` | Perpetua-Tools | Rolling probe history |
| `.state/routing.json` | Perpetua-Tools | Last known good routing state (warm cache source) |
| `start.sh` | orama-system | Process manager; reads PT routing state |

---

## 10. Extension Checklist

When adding a new backend or scenario:

- [ ] Add value to `StartupScenario` enum in `startup_intelligence.py`
- [ ] Add `FallbackChain` entry to `SCENARIO_TABLE`
- [ ] Update `classify_scenario()` priority rules (document the new rule)
- [ ] Add probe call in `initialize_environment()` (unpack as `(bool, latency)`)
- [ ] Add latency key to `_record_startup()` call
- [ ] Update `build_routing_hints()` if the new probe needs adaptive timeout
- [ ] Add at least 3 tests: happy-path, miss-path, classify branch
- [ ] Update this SKILL.md scenario table (§1) and diagnostic section (§8)
