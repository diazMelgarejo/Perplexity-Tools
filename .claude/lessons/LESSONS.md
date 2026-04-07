# Lessons — Shared Knowledge Base

> **Canonical path**: `.claude/lessons/LESSONS.md` (same in PT and ultrathink-system)
> **Purpose**: GitHub-auditable persistent memory across all ECC, AutoResearcher, and Claude sessions.
>
> **Rules**:
> - Read this file at the start of every session
> - Append new learnings before ending a session
> - Keep entries dated and agent-tagged
> - Cross-reference companion repo: [ultrathink-system/.claude/lessons/LESSONS.md](https://github.com/diazMelgarejo/ultrathink-system/blob/main/.claude/lessons/LESSONS.md)

## continuous-learning-v2

This repo uses [continuous-learning-v2](https://github.com/affaan-m/everything-claude-code/tree/main/skills/continuous-learning-v2) for all agents.
Instincts: `.claude/homunculus/instincts/inherited/Perplexity-Tools-instincts.yaml`
Import command: `/instinct-import .claude/homunculus/instincts/inherited/Perplexity-Tools-instincts.yaml`

---

## Sessions Log

<!-- Append entries below. Format:
## YYYY-MM-DD — <agent: ECC | AutoResearcher | Claude> — <brief topic>
### What was learned
- bullet points
### Decisions made
- bullet points
### Open questions
- bullet points
-->

---

## 2026-04-07 — Claude — Idempotent installs: subprocess permissions + model auto-discovery

### What was learned

- **`capture_output=True` silences bootstrap scripts** — never use it in user-facing install flows; let stdout/stderr stream through so the user can see progress and errors
- **`npm install -g` does not guarantee execute bits** on all platforms/nvm configs — the installed binary exists and is found by `shutil.which()` but raises `PermissionError: [Errno 13]` when Python tries to execute it via `subprocess.run()`
- **`PermissionError` is NOT a `subprocess.CalledProcessError`** — must be caught separately; an unhandled `PermissionError` crashes the entire bootstrap with a traceback instead of a clean error message
- **Hardcoded model names break inference** — LM Studio returns `400 Bad Request` and Ollama returns `404 Not Found` when the configured model isn't loaded; always resolve via `GET /v1/models` (LM Studio) or `GET /api/tags` (Ollama) before sending inference requests
- **Windows GPU models cannot be called on Mac memory** — Windows LM Studio at `192.168.254.103:1234` must be called remotely over LAN; `192.168.254.101:1234` is Mac's own LM Studio instance — never cross these
- **AgentTracker `agents.json` must not share path with routing state** — flat routing dicts (`{"mode": "distributed"}`) cause `AgentRecord(**v)` to raise `TypeError: argument after ** must be a mapping, not str`; `_load()` must `isinstance(v, dict)` guard every entry

### Decisions made

- `_resolve_ollama_model()` and `_resolve_lmstudio_model()` added to `scripts/launch_researchers.py` — called at startup of each researcher before `tracker.register()`; remap to first available model if preferred is absent
- `openclaw_bootstrap.py` auto-`chmod +x` the openclaw binary immediately after `npm install -g` if execute bit is missing
- `AgentTracker._load()` now skips non-dict entries and rewrites the file clean rather than crashing

### Prevention Rules (encode in all future idempotent installs)

1. No `capture_output=True` in bootstrap/install subprocess calls
2. After `npm install -g <pkg>`, always verify and fix `S_IXUSR` before running the binary
3. Catch `PermissionError` separately from `CalledProcessError` in every subprocess block
4. Never hardcode model names — query `/v1/models` or `/api/tags` at runtime
5. Keep AgentTracker's `agents.json` on a distinct path from any routing/config state file
6. All typed-record `_load()` methods must `isinstance(v, dict)` before `**v` unpacking

### Commits
- `3c9a4a8` (UTS) — fix(bootstrap): handle PermissionError + auto chmod +x after npm install
- `23bd01d` (UTS) — fix(bootstrap): remove capture_output=True
- `ffb1be0` (PT)  — fix(researchers): auto-discover loaded model via /v1/models + /api/tags
- `d9e4f50` (PT)  — fix(tracker): handle stale routing data in agents.json

---

## 2026-04-07 — Claude — Device identity + GPU crash recovery

### What was learned

**1. `127.0.0.1` and a LAN IP can point to the same physical machine**
- `WINDOWS_IP=192.168.254.101` (the Mac's own LAN IP) would probe successfully and spawn a second researcher on the same device, treating one Mac as a distributed two-node cluster
- OS routing tables encode this: opening a `SOCK_DGRAM` socket toward `8.8.8.8` without sending packets reveals the outbound LAN IP — compare against configured endpoints
- Fix: `_get_local_ips()` uses hostname resolution + UDP routing trick; `_is_local_endpoint()` checks if a URL host is in that set; all Windows probes that match a local IP are zeroed out

**2. One role per physical device is a hard constraint**
- If both Mac Ollama (`127.0.0.1:11434`) and Mac LM Studio (`192.168.254.101:1234`) are up and on the same machine, picking both as independent "backends" would load two models simultaneously on the same GPU/RAM
- Resolution: Ollama takes precedence; LM Studio treated as same-device and ignored when Ollama is running

**3. Rapid model reload after crash burns GPU**
- When a model crashes (404, 500) or is loading (503), the next iteration fires immediately or after `interval` seconds — enough to trigger repeated load/unload cycles under GPU pressure
- Fix: classify errors by HTTP status code (503=loading, 404=unloaded, ConnectError=offline) and replace normal `asyncio.sleep(interval)` with a 30-second cooldown (`CRASH_RECOVERY_SECS`)

**4. Terminal feedback during crash recovery is essential**
- Silent waiting with no output makes it impossible to tell if the system is frozen or recovering
- Fix: `_wait_with_progress(seconds, role, reason)` renders a live ASCII progress bar with role name, crash classification, and per-second countdown

### Prevention Rules (encode in all future multi-device orchestrators)

1. **Always call `_get_local_ips()` before trusting any "remote" endpoint** — use the UDP routing trick (no packets sent) to discover the machine's outbound LAN IP
2. **One role per physical device** — zero out any "remote" probe whose host IP is in `local_ips`
3. **On same device: one inference backend** — if both Ollama and LM Studio are local and running, pick one deterministically (Ollama > LM Studio)
4. **Crash recovery must be at least 30 seconds** — GPU model load/unload cycles need this buffer; never retry immediately after a 503/404/500 from an inference backend
5. **Classify errors before sleeping** — 503 ≠ 404 ≠ ConnectError; each needs a different user-facing message and potentially different recovery time
6. **Show a progress bar during recovery** — `asyncio.sleep(N)` is invisible; use a 1-second tick loop with `\r` overwrite so the user knows the system is alive

### Implementation
- `_get_local_ips()` + `_is_local_endpoint()` in `agent_launcher.py`
- Device-identity guard block in `initialize_environment()` — runs after async probes, before routing decisions
- `CRASH_RECOVERY_SECS = 30` constant + `_wait_with_progress()` in `scripts/launch_researchers.py`
- Error classification: HTTP status code from `exc.response.status_code` via `getattr` chain (safe on non-HTTP exceptions)

### Commits
- `8af62f5` (PT) — feat(routing): one-role-per-device guard + GPU crash recovery cooldown

---

## 2026-04-07 — Claude — Idempotent gateway discovery (commandeer-first bootstrap)

### What was learned

- **Probe before start**: always check ALL candidate ports before launching any daemon — the running service may be a different fork (AlphaClaw, custom proxy) on a non-default port
- **Commandeer = use + refresh config, no restart** — if a gateway answers `/health` or `/v1/models`, write updated config/workspaces but never call the daemon start command
- **Never evict loaded models** — calling `onboard --install-daemon` or equivalent when a gateway is running risks restarting the process and unloading models from GPU VRAM
- **Set a discoverable env var** after commandeering so all consumers (orchestrators, researchers) use the correct URL without repeating the discovery probe
- **Protocol probe, not process check** — identify gateways by HTTP interface (`/health`, `/v1/models`), not by process name; this is fork-agnostic

### Prevention Rules

1. All bootstrap scripts: probe candidate ports FIRST, install/start LAST
2. Commandeer any compatible service found — do not start a duplicate
3. Never restart a running daemon in a bootstrap path
4. Set `*_GATEWAY_URL` / `*_ENDPOINT` env var after discovery for downstream use
5. Candidate port list must be env-configurable (`OPENCLAW_EXTRA_PORTS`, etc.)

### Commits
- `6bc40d0` (UTS) — feat(bootstrap): probe all candidate ports and commandeer any running gateway
