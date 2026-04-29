# Lessons — Perpetua-Tools

## 2026-04-26 — Hardware Model Affinity Incident

**Context:**
`orama-system/scripts/discover.py` was writing unfiltered LM Studio model lists
to `openclaw.json`. This could cause `lmstudio-mac` to advertise Windows-only
27B/26B models, creating a hardware damage risk on the M2 Pro, while
`lmstudio-win` could advertise Mac-only MLX / Apple Silicon models.

**Root cause:**
Discovery trusted endpoint responses without cross-referencing a hardware policy.

**Defense-in-depth solution:**
- L1: `discover.py` filters through `Perpetua-Tools/config/model_hardware_policy.yml`
  before writing discovery state, `openclaw.json`, or `.env.lmstudio`.
- L2: `utils/hardware_policy.py`, `alphaclaw_manager.py`, and `agent_launcher.py`
  enforce affinity before routing/spawn decisions.
- L3: `api_server.py` returns HTTP 400 `HARDWARE_MISMATCH` at the API boundary.

**Canonical policy file:** `config/model_hardware_policy.yml`

**Known hallucinations removed:** `qwen3-coder-14b` and `gemma4:e4b` appeared in
AI-generated drafts of this plan. They are NOT verified model IDs in this system.
Do not re-add them.

**Status:** Implemented 2026-04-26.

**Follow-up — unified CLI/GUI management:**
Do not multiply human entry points. Hardware policy validation is exposed through
the existing orama CLI (`./start.sh --hardware-policy`, `./start.sh --status`)
and the existing Orama Portal (`http://localhost:8002`, Hardware Policy & Safe
Defaults section). `scripts/hardware_policy_cli.py` is a helper used by the
existing CLI, tests, and agents — not a separate product surface.

---

> **Canonical path**: `docs/LESSONS.md`
> **Previous path**: `.claude/lessons/LESSONS.md` (now redirects here)
> **Purpose**: GitHub-auditable persistent memory across all ECC, AutoResearcher, and Claude sessions.
> **Cross-repo companion**: [orama-system/docs/LESSONS.md](https://github.com/diazMelgarejo/orama-system/blob/main/docs/LESSONS.md)
>
> **Rules**:
> - Read this file at the start of every session
> - Append new learnings before ending a session
> - Keep entries dated and agent-tagged (`ECC | AutoResearcher | Claude`)
> - For organized, deep-dive explanations see the **[wiki →](wiki/README.md)**
> - For agent behavioral rules see **[SKILL.md →](../SKILL.md)**

---

## continuous-learning-v2

This repo uses [continuous-learning-v2](https://github.com/affaan-m/everything-claude-code/tree/main/skills/continuous-learning-v2).
Instincts: `.claude/homunculus/instincts/inherited/Perpetua-Tools-instincts.yaml`
Import command: `/instinct-import .claude/homunculus/instincts/inherited/Perpetua-Tools-instincts.yaml`

---

## Sessions Log

<!-- Append entries below. Format:
## YYYY-MM-DD — <agent: ECC | AutoResearcher | Claude> — <brief topic>
### What was learned
### Decisions made
### Open questions
-->

---

## 2026-04-13 — Claude — Startup fix: IP detection, stdin deadlock, concurrent backend probing

### Learned

- **Abort trap: 6 root cause**: `_gather_alphaclaw_credentials()` spawned a daemon thread calling `input()`. After `t.join(30)` timed out the thread was still alive and held the stdin `BufferedReader` lock; Python interpreter shutdown tried to flush/close that reader → SIGABRT. Three-layer fix: (1) `sys.stdin.isatty()` guard in Python skips the daemon thread in non-interactive mode, (2) `</dev/null` in start.sh redirects stdin so `input()` gets instant EOFError, (3) `stdin=subprocess.DEVNULL` on the AlphaClaw gateway `Popen` prevents the node process from inheriting the broken fd.

- **IP misconfiguration was silent**: `agent_launcher.py` read `MAC_LMS_HOST`/`WINDOWS_IP` from env but neither was exported by start.sh or present in `.env`. Fallback hard-coded defaults (`.103`, `.100`) were always used. Actual LAN addresses are `.110` (Mac LM Studio) and `.108` (Windows).

- **`.env.local` had wrong values**: `WINDOWS_IP=192.168.254.101` (off by several octets), `WINDOWS_PORT=1234` (LM Studio port incorrectly overriding the Ollama port — `REMOTE_WINDOWS_URL` pointed at LM Studio instead of Ollama). Fixed to `.108` / `11434`.

- **`agent_launcher.py` never called `load_dotenv()`**: it only saw shell-exported vars. Added `load_dotenv(".env")` + `load_dotenv(".env.local", override=True)` so `.env` files are always honoured.

- **`asyncio.create_task()` fires immediately; `gather()` blocks**: firing all 4 backend probes as tasks at t=0 and awaiting in two phases (local first, then LAN) gives correct ordering without sequential delay.

- **`_persist_detected_ips()`**: after each successful probe run, confirmed live endpoints are written back to `.env`. This makes the configuration self-correcting across restarts.

### Decided

- Hard-coded defaults in `agent_launcher.py` updated: `.110` Mac LM Studio, `.108` Windows.
- `network_autoconfig.py` `preferred_ips` updated to `.110` / `.108`.
- `LM_STUDIO_MAC_ENDPOINT` in both repo `.env` files updated to `http://192.168.254.110:1234`.
- `.env.local` corrected: `WINDOWS_IP=192.168.254.108`, `WINDOWS_PORT=11434`.

### Open

- Windows Ollama at `.108:11434` is probably not running — verify `windows_ollama_ok: false` path produces clean routing.json with `coder_backend: windows-lmstudio`.

→ [wiki/06-startup-ip-detection.md](wiki/06-startup-ip-detection.md)

---

## 2026-04-20 — Claude — Gate 1: Three-repo adapter, AlphaClaw HTTP client, alphaclaw_manager.py

### Learned

**Architecture decisions (do not re-debate):**
- `"type": "module"` in `packages/alphaclaw-adapter/package.json` conflicted with `require()` in all source files (copied from AlphaClaw, which is CJS). Fix: remove `"type": "module"`. Keep everything CommonJS in this package.
- `spawnSync` with `detached:true` does NOT actually detach — the parent blocks until the child exits. Always use `spawn` (not `spawnSync`) then `child.unref()` for detached background processes.
- Session cookies from AlphaClaw's `/api/auth/login` arrive in `res.headers["set-cookie"]` as an array. Must `map(c => c.split(";")[0]).join("; ")` to extract the key=value without attributes (Secure, HttpOnly, Path).

**AlphaClaw auth model (SETUP_API_PREFIXES):**
- Two auth tiers exist: "setup-allowlisted" (`/api/status`, `/api/gateway*`, `/api/restart-status`) accessible without a full session, and "session²" (`/api/models`, `/api/env`, `/api/watchdog/*`) requiring a cookie from `POST /api/auth/login`. Always probe via `/health` first (no auth), then setup-allowlisted endpoints, then login before calling session² endpoints.

**orchestrator/alphaclaw_manager.py pattern:**
- The `--env-only` flag pattern (print `export KEY='val'` lines, caller does `eval "$(...)"`) is the cleanest way to propagate PT-resolved env vars into a bash script without a temp file or JSON parsing in bash.
- `--resolve --env-only` pipes through `tee /dev/stderr` so progress messages appear in the terminal while `grep '^export '` captures only the eval-able lines.
- `subprocess.run()` with `capture_output=False` lets the Python child's stdout/stderr stream to the terminal in real time — critical for long-running operations like AlphaClaw bootstrap.

**start.sh thinning rule:**
- Sections 2a (backend probe) and 2c (mode determination) were gateway decision logic — they belong in PT, not in orama. If a shell script is making gateway routing decisions, it violates the PT-is-authoritative invariant.
- The thinned start.sh pattern: resolve via PT (`eval "$PT_ENV_EXPORTS"`), then unconditionally start services. The shell script is now a pure process manager, not a policy engine.

**Smoke test structure:**
- Group tests by auth tier (no-auth → setup-allowlisted → session-auth → watchdog) to match the contract document. This makes it obvious which section a failure belongs to.
- Mark destructive tests (restartGateway, watchdogRepair) as `null` (SKIP) by default; gate behind `SMOKE_DESTRUCTIVE=1` env var.
- Exit code 1 on any FAIL so CI can catch regressions.

**FUSE mount git limitations (still applies at Gate 1):**
- `git add`, `git commit`, `git push` in the sandbox FUSE-mounted paths often fail with `index.lock` or `Resource deadlock avoided`. Always provide Mac terminal commands for git operations.

### Decisions Made

- `packages/alphaclaw-adapter/src/index.js` is the **authoritative Node.js HTTP client** — 20+ exported functions, module-level session state, commandeer-first `discoverPort()`, proper detached `startServer()`.
- `orchestrator/alphaclaw_manager.py` is the **authoritative Python lifecycle manager** — absorbs start.sh §2a (backend probe) and §2c (mode determination). orama delegates entirely to this module.
- `packages/alphaclaw-adapter/scripts/smoke-test.js` is the **Gate 1 acceptance test** — run against live AlphaClaw before marking Gate 1 fully verified.
- Gate 1 is structurally complete. The one remaining step before Gate 1 is "fully" done: run smoke-test.js against a live AlphaClaw instance and register the MCP server in claude mcp.

### Open

- MCP server registration still pending: `claude mcp add --transport stdio alphaclaw -- node packages/alphaclaw-adapter/src/mcp/server.js`
- `packages/local-agents/tests/client.test.js` (Vitest) not yet run — pending Gate 1 verification step
- `lib/mcp/` and `lib/agents/` in AlphaClaw `feature/MacOS-post-install` not yet tagged for removal (wait for smoke-test green)
- `openclaw_bootstrap.py` in orama scope-down to apply-config only is Gate 2 work

→ [docs/MIGRATION.md §Gate 1](MIGRATION.md)
→ [docs/adapter-interface-contract.md](adapter-interface-contract.md)
→ [docs/adr/ADR-001-three-repo-adapter-architecture.md](adr/ADR-001-three-repo-adapter-architecture.md)

---

## 2026-04-07 — Claude — Idempotent installs: subprocess permissions + model auto-discovery

### What was learned

- **`capture_output=True` silences bootstrap scripts** — never use in user-facing install flows; let stdout/stderr stream through
- **`npm install -g` does not guarantee execute bits** — `shutil.which()` finds the binary but `subprocess.run()` raises `PermissionError: [Errno 13]`; catching only `CalledProcessError` leaves it unhandled
- **Hardcoded model names break inference** — LM Studio returns `400`, Ollama returns `404` when model isn't loaded; always resolve via `/v1/models` or `/api/tags` at runtime
- **Windows GPU models cannot be called on Mac** — LAN isolation required; `192.168.254.103` (Windows) and `192.168.254.101` (Mac LMS) are distinct physical devices
- **AgentTracker `agents.json` must not share path with routing state** — flat routing dicts cause `AgentRecord(**v)` `TypeError`

### Decisions made

- `_resolve_ollama_model()` and `_resolve_lmstudio_model()` added — query backend before registering agent
- `openclaw_bootstrap.py` auto-`chmod +x` after `npm install -g` if execute bit missing
- `AgentTracker._load()` skips non-dict entries and rewrites file clean

### Commits
- `ffb1be0` (PT) — fix(researchers): auto-discover loaded model via /v1/models + /api/tags
- `d9e4f50` (PT) — fix(tracker): handle stale routing data in agents.json

→ [wiki/02-idempotent-installs.md](wiki/02-idempotent-installs.md)

---

## 2026-04-07 — Claude — Device identity + GPU crash recovery

### What was learned

1. **`127.0.0.1` and a LAN IP can point to the same physical machine** — UDP routing trick reveals outbound LAN IP; compare against configured endpoints before assigning roles
2. **One role per physical device** — if both Mac Ollama and Mac LM Studio are up on the same machine, two models would load on the same GPU; Ollama takes precedence
3. **Rapid model reload after crash burns GPU** — classify by HTTP status (503=loading, 404=unloaded, ConnectError=offline); enforce 30s cooldown minimum
4. **Terminal feedback during crash recovery is essential** — ASCII progress bar with role + countdown

### Prevention Rules

1. Always call `_get_local_ips()` before trusting any "remote" endpoint
2. One role per physical device — zero out probes whose host IP matches local IPs
3. On same device: Ollama > LM Studio deterministically
4. Crash recovery ≥ 30 seconds
5. Classify errors before sleeping — 503 ≠ 404 ≠ ConnectError
6. Show progress bar during recovery

### Commits
- `8af62f5` (PT) — feat(routing): one-role-per-device guard + GPU crash recovery cooldown

→ [wiki/03-device-identity.md](wiki/03-device-identity.md)

---

## 2026-04-07 — Claude — Idempotent gateway discovery (commandeer-first bootstrap)

### What was learned

- Probe before start: always check ALL candidate ports before launching any daemon
- Commandeer = use + refresh config, no restart — calling `onboard --install-daemon` when a gateway is running risks restarting and evicting models from GPU VRAM
- Protocol probe, not process check — identify by HTTP interface (`/health`, `/v1/models`), not by process name

### Prevention Rules

1. All bootstrap scripts: probe candidate ports FIRST, install/start LAST
2. Commandeer any compatible service found — do not start a duplicate
3. Never restart a running daemon in a bootstrap path
4. Set `*_GATEWAY_URL` / `*_ENDPOINT` env var after discovery for downstream use
5. Candidate port list must be env-configurable (`OPENCLAW_EXTRA_PORTS`, etc.)

### Commits
- `6bc40d0` (UTS) — feat(bootstrap): probe all candidate ports and commandeer any running gateway

→ [wiki/04-gateway-discovery.md](wiki/04-gateway-discovery.md)

---

## 2026-04-11 — Claude — AutoResearcher migration: karpathy → uditgoenka plugin

### Key Changes

1. **`AUTORESEARCH_REMOTE` is now an env var** (not hardcoded):
   ```bash
   AUTORESEARCH_REMOTE=https://github.com/uditgoenka/autoresearch.git  # default
   AUTORESEARCH_BRANCH=main  # default sync branch (was hardcoded 'master')
   ```

2. **Plugin install is primary mode:**
   ```bash
   claude plugin marketplace add uditgoenka/autoresearch
   claude plugin install autoresearch@autoresearch
   ```

3. **GPU runner is now secondary** (Verify substrate for `ml-experiment` task types only)

4. **`uv sync --dev`** replaces bare `pip install` in all bootstrap paths

5. **Valid Windows model names**:
   - `Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2` — valid 27B identifier
   - `Qwen3.5-27B-Instruct` **DOES NOT EXIST** — never use this string

→ [wiki/05-autoresearcher-migration.md](wiki/05-autoresearcher-migration.md)

---

## 2026-04-12 — Claude — 48-hour multi-agent sprint: collaboration patterns + version registry

### Version Number Registry — All Canonical Locations

**Current version: `0.9.9.7`.** Do NOT bump without explicit user instruction.

#### Perpetua-Tools (PT)

| File | Field |
|------|-------|
| `pyproject.toml:12` | `version = "0.9.9.7"` |
| `orchestrator/__init__.py:5` | `__version__ = "0.9.9.7"` |
| `orchestrator/fastapi_app.py:74` | `version="0.9.9.7"` |
| `orchestrator/fastapi_app.py:295` | `"version": "0.9.9.7"` (health JSON) |
| `orchestrator.py:97` | `VERSION = "0.9.9.7"` |
| `config/devices.yml:6` | `version: "0.9.9.7"` |
| `config/models.yml:6` | `version: "0.9.9.7"` |
| `SKILL.md:3` | `**Version:** \`v0.9.9.7\`` |
| `README.md:1,170` | `v0.9.9.7` |

### Multi-Agent Collaboration Protocol

1. **Read `docs/LESSONS.md` first** — scope claims are written here
2. **Scope claim** — append `## [IN PROGRESS] YYYY-MM-DD — Claude — <topic>` before touching files
3. **Additive changes** — prefer appending over rewriting; no conflict risk
4. **Commit body must name changed constants/APIs** — the only async channel between agents
5. **Never hardcode LAN IPs in source defaults** — `127.0.0.1` in code, real IPs in `.env` only
6. **One canonical source per constant** — two files defining the same IP will diverge
7. **Test isolation** — `autouse` fixture that restores module-level state after `importlib.reload()`

### Key Bugs Fixed This Sprint

- **Stash pop after rebase** — `alphaclaw_bootstrap.py` got both versions appended; required Python line-by-line surgery
- **Orphan branch in UTS** — `git merge-base` returned exit 1; fixed with `git reset --hard origin/main`
- **Hardcoded LAN IP broke CI** — `192.168.254.103` in fastapi_app.py defaults broke `test_health_uses_plain_string_defaults`
- **Test module state contamination** — `importlib.reload()` without restore leaked `AUTORESEARCH_DEFAULT_BRANCH = "dev"` across tests

### Pre-Commit Checklist

```bash
git fetch origin main
git log --oneline HEAD..origin/main          # changes by other agents
grep -rn "192\.168\." --include="*.py" | grep -v "test_\|#\|LESSONS\|\.env"
python -m pytest -q
```

### Commits
- `71a15f7` (PT) — fix(health): restore 127.0.0.1 loopback defaults

→ [wiki/07-multi-agent-collab.md](wiki/07-multi-agent-collab.md)

---

## 2026-04-13 — Claude — alphaclaw macOS compatibility patches + idempotent setup automation

### Error → Root Cause Map

| Startup error | Root cause | Fix |
| -------------- | ---------- | --- |
| `gog install skipped: Permission denied /usr/local/bin/gog` | `/usr/local/bin/` is root-owned on macOS | Change dest to `~/.local/bin/gog` |
| `Cron setup skipped: ENOENT /etc/cron.d/openclaw-hourly-sync` | `/etc/cron.d/` is Linux-only | macOS: use `crontab -l` user crontab |
| `systemctl shim skipped: EACCES /usr/local/bin/systemctl` | Linux/Docker-only shim | Wrap in `if (os.platform() !== "darwin")` |
| `git auth shim skipped: EACCES /usr/local/bin/git` | git shim dest hardcoded to root-owned path | Change to `~/.local/bin/git` |
| `Gateway timed out after 30s` | gateway exits on JSON schema error (`models` array undefined) | Add `models[]` arrays to ollama providers |

### `~/.local/bin` Precedence Pattern

PATH order on macOS: `~/.local/bin` (pos 4) → `/usr/local/bin` (pos 9). Installing to `~/.local/bin` = user-writable shadow of system paths. No `sudo` required.

### Idempotent Setup

`orama-system/setup_macos.py` (called from `start.sh` on every boot):
- Creates `~/.local/bin`, adds it to PATH in `~/.zshrc`
- Validates `~/.openclaw/openclaw.json` — adds `models[]` if missing
- Applies 6 alphaclaw.js patches idempotently (detect string guards)

→ [wiki/08-macos-alphaclaw-compat.md](wiki/08-macos-alphaclaw-compat.md)

---

## Wiki

All lessons above are expanded with root causes, exact fixes, and verification commands:

| # | Page | Topic |
| --- | --- | --- |
| 01 | [CI Dependencies](wiki/01-ci-deps.md) | pip extras, hatchling, pyproject.toml guard |
| 02 | [Idempotent Installs](wiki/02-idempotent-installs.md) | execute bits, capture_output, model discovery |
| 03 | [Device Identity](wiki/03-device-identity.md) | one-role-per-device, GPU crash recovery |
| 04 | [Gateway Discovery](wiki/04-gateway-discovery.md) | commandeer-first bootstrap, candidate ports |
| 05 | [AutoResearcher Migration](wiki/05-autoresearcher-migration.md) | uditgoenka plugin, uv sync, valid model names |
| 06 | [Startup IP Detection](wiki/06-startup-ip-detection.md) | stdin deadlock, load_dotenv, asyncio probing |
| 07 | [Multi-Agent Collab](wiki/07-multi-agent-collab.md) | version registry, scope claims, orphan branches |
| 08 | [macOS alphaclaw Compat](wiki/08-macos-alphaclaw-compat.md) | EACCES fixes, ~/.local/bin, setup_macos.py |

## [2026-04-21] Configuration Portability: OS-Agnostic Paths
*(synced from [AlphaClaw `feature/MacOS-post-install` → `7-Lessons.md`](https://github.com/diazMelgarejo/AlphaClaw/blob/feature/MacOS-post-install/7-Lessons.md))*

- **Problem**: Absolute paths (e.g. `/Users/user/...`) in `openclaw.json` break cross-platform deployments.
- **Solution**: Always use `${HOME}` variables in configuration templates. AlphaClaw gateway and onboarding runtime MUST resolve these relative to the OS-specific home directory.
- **Rule**: Enforce `${HOME}` in all `openclaw.json.template` and active config files. No hardcoded usernames or absolute paths.

---

## [2026-04-21] Core Policy: Additive Ghost Orchestration
*(synced from [AlphaClaw `feature/MacOS-post-install` → `7-Lessons.md`](https://github.com/diazMelgarejo/AlphaClaw/blob/feature/MacOS-post-install/7-Lessons.md))*

- **Additive Configuration**: Never overwrite `openclaw.json`. Always read → deep-merge (spread) → write back.
- **Upstream Autonomy**: PT and orama act as ghost orchestrators — absorb and extend OpenClaw/AlphaClaw features without becoming structural dependencies.
- **Non-Destructive Injection**: Use native onboarding hooks (e.g. `writeManagedImportOpenclawConfig`) to inject PT/orama configs.
- **Portability**: Always use `${HOME}` for all path construction — OS-agnostic across Mac/Win/Linux.

---

## [2026-04-22] Symlink Portability & Validation
*(synced from [AlphaClaw `feature/MacOS-post-install` → `7-Lessons.md`](https://github.com/diazMelgarejo/AlphaClaw/blob/feature/MacOS-post-install/7-Lessons.md))*

- **Requirement**: Git must track symlinks as Mode 120000. Use `git ls-files -s` to verify.
- **Automation**: Startup scripts (`start.sh`) MUST validate symlinks. If a link is missing or broken, the script should attempt to recreate it or provide clear instructions on where the missing sibling dependency should live.
- **Agnostic Pathing**: Always use relative paths in symlinks (e.g., `../sibling`) rather than absolute paths to ensure portability across different clones.

---

## 2026-04-26 — Claude — Cross-repo import pattern for hardware_policy

### What was learned

**utils/hardware_policy.py is PT-owned; orama imports via sys.path**
The canonical approach: orama's `api_server.py` and `scripts/discover.py` both resolve
`PERPETUA_TOOLS_ROOT` (env var with sibling-dir fallback) and call
`sys.path.insert(0, PERPETUA_TOOLS_ROOT)` to import `utils.hardware_policy` at runtime.
This avoids packaging the module twice or adding a git submodule.

**Fallback must be visible in logs**
If `PERPETUA_TOOLS_ROOT` path doesn't exist or the import fails, the except block
now emits `logger.warning(...)` with the resolved path. Operators can see when
enforcement is silently disabled.

**pre-commit hook blocks hallucinated model IDs**
`scripts/check_no_hallucinated_models.py` is registered as a pre-commit hook in both repos.
It blocks `qwen3-coder-14b` and `gemma4:e4b` — IDs that appeared in AI-generated plan drafts
but are not verified model IDs in this system. Add to this list whenever a hallucination is
discovered in any plan or code review.

### Decisions made

- PT owns `utils/hardware_policy.py` and `config/model_hardware_policy.yml`
- orama consumes via sys.path injection, not packaging or submodule
- `shared:` section intentionally empty until both machines are verified online

### Follow-up

- Populate `shared:` section after live `discover.py --status` run (Part 2 plan)
- Document `PERPETUA_TOOLS_ROOT` in both repos' `.env.example`

---

# 2026-04-27 — Part 2 Complete: Affinity Key Normalization, Disaster Recovery, Gemini Plan Review

## Changes landed

**G3 — device_affinity → affinity key rename (PT side):**
- `config/routing.yml` autoresearch routes: `device_affinity` → `affinity`
- Value `win-rtx3080` preserved — future Windows hardware profiles (e.g. win-rtx4090) share the windows_only blocklist but need distinct whitelists. Device-specific affinity is the extension point. **Never normalize `win-rtx3080` to generic `win`.**
- Fixed stale test: `ULTRATHINK_ENDPOINT` → `ORAMA_ENDPOINT` (the rename had happened in routing.yml but the test didn't track it)
- Regression guard: `test_routing_affinity_keys_normalized` blocks future re-introduction of `device_affinity` key

**G1 — shared: section:**
- Commented out in `config/model_hardware_policy.yml` with TODO pointing to Part 2 Phase 5
- Added `_POLICY_CACHE` autouse fixture to clear module-level cache between tests (prevents test-ordering contamination)
- Parametrized test covers all 3 YAML variants (commented-out, absent, explicit-empty) × both parsers (PyYAML + `_simple_policy_parse`)

**G2 — PERPETUA_TOOLS_ROOT:**
- Documented in `.env.example` with cross-repo usage context

## Disaster Recovery Pattern (owned by orama, mirrors here for cross-repo context)

`HardwarePolicyResolver` in `orama/api_server.py` implements:
1. **PT-first**: import from `PERPETUA_TOOLS_ROOT` → authoritative
2. **Cache fallback**: `config/hardware_policy_cache.yml` → degraded (CRITICAL warning)
3. **Hard fail if cache missing**: never silently skip enforcement

**Key invariant for PT:** orama will ALWAYS try PT first and defer to PT's decisions. The cache is strictly a last resort for DR scenarios, not a way to bypass PT. PT remains authoritative — orama will call back to PT on every start and include `policy_source` in response metadata so ops can detect when the fallback was used.

## Gemini v3.1 Plan Review

**Accepted:** G2 (env docs) and G4 (hallucination purge — already done).

**Rejected — symlink proposal:** `orama/utils/hardware_policy.py → PT/utils/hardware_policy.py`. Fragile: breaks on Windows (no Unix symlinks), breaks in Docker/CI when repos at different mount paths, breaks when repos cloned to different locations. sys.path injection is more portable and already works.

**Rejected — remove _simple_policy_parse:** This fallback exists for PyYAML-absent environments. Removing it trades elegance for fragility.

## Test counts

- PT: 24/24 (16 → +8 new tests)
- orama: 23/23 (16 → +7 new schema tests)

---

## Session 2026-04-27b — Agent Automation + Portal Integration

### Codex PTY Automation Pattern (CRITICAL — add to all agent skills)

**Problem:** Codex `--full-auto` requires a TTY. Spawning from Python subprocesses fails with "stdin is not a terminal".

**Automated solution using `pty.openpty()`:**
```python
import pty, select, os, subprocess

master_fd, slave_fd = pty.openpty()
proc = subprocess.Popen(
    ["codex", "--full-auto", task],
    stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
    close_fds=True, cwd=str(repo_root),
)
os.close(slave_fd)
# Collect output via master_fd with select() + timeout
```
**This makes Codex 100% automatable — no human terminal needed, works from Claude Code, CI, FastAPI, or any Python subprocess.**

See: `orama-system/scripts/spawn_agents.py → _dispatch_codex()`

### Gemini CLI Fix
```bash
# Create wrapper in ~/.local/bin/gemini:
#!/usr/bin/env bash
exec /path/to/nvm/v24/bin/node /path/to/nvm/v24/bin/gemini "$@"
```
Fixes `??= SyntaxError` when shell resolves `node` to v14.
Auto-created by `scripts/setup_codex.sh` on every stack startup.

### Tools Available (cross-session reference)
| Tool | Status | How to use |
|------|--------|-----------|
| Codex | ✓ via PTY | `spawn_agents.py --agent codex` |
| Gemini CLI | ✓ via wrapper | `spawn_agents.py --agent gemini` or `~/.local/bin/gemini -p "..."` |
| LM Studio Mac | ✓ when .110 online | `spawn_agents.py --agent lmstudio-mac` |
| LM Studio Win | ✓ when .101 online | `spawn_agents.py --agent lmstudio-win` (GPU serialized) |
| All agents | parallel + serial | `spawn_agents.py --agent all` |

### Module Loading Pattern (sys.modules registration)
When loading a Python module with `importlib.util.exec_module` and it contains dataclasses:
```python
mod = importlib.util.module_from_spec(spec)
sys.modules['module_name'] = mod  # MUST register before exec_module
spec.loader.exec_module(mod)       # otherwise dataclass field annotations fail
```


## [2026-04-27] Hardware × Agent Matrix Test — Full Results

### Confirmed Facts

- **Model IDs are case-sensitive** in LM Studio. Config `Qwen3.5-9B-MLX-4bit` fails with HTTP 400.
  Correct IDs (all lowercase): `qwen3.5-9b-mlx`, `qwen3.5-27b-claude-4.6-opus-reasoning-distilled-v2`
  Also: Mac LM Studio does NOT have the `-4bit` suffix in the model ID.

- **openclaw CLI requires Node.js ≥ v22**. System default (v14.21.3) fails instantly.
  Fix: `export PATH=$HOME/.nvm/versions/node/v24.14.1/bin:$PATH` or use full path.
  Installed at: `/Users/lawrencecyremelgarejo/.nvm/versions/node/v24.14.1/bin/openclaw`

- **Both LM Studio nodes load the same models** (MLX 9B and GGUF 27B):
  - Mac `localhost:1234`: `qwen3.5-9b-mlx` (ctx=56384, MLX), `qwen3.5-27b-...` (ctx=131072, GGUF)
  - Win `192.168.254.103:1234`: `qwen3.5-27b-...` (ctx=131072, GGUF), `qwen3.5-9b-mlx` (ctx=56384)

- **Both models are extended thinking/reasoning models.** They generate `<think>` blocks
  (stored in `reasoning_content`) before visible output. This makes agent turns slow:
  - Win 27B GGUF (RTX 3080): 107–130s per agent turn ✅ succeeds
  - Mac 9B MLX: 105–308s per agent turn ✅ succeeds (via Gemini fallback on long turns)
  - Direct API calls (tiny prompt): Mac 9B ~8–15s, Win 27B ~3s

- **Mac 9B stall root cause**: Parallel=1 + reasoning model generates large think blocks.
  Multiple rapid test requests queue up in LM Studio; each waits its turn. Clear by restarting
  LM Studio or waiting ~2 min for queue to drain.

- **Thinking models return empty `text` field** for simple prompts — response is in
  `reasoning_content`. The `openclaw agent --json` output `text` field is empty; check
  `reasoning_content` or use `--thinking minimal` to get brief visible responses.

- **commandTimeout must be ≥ 300s** for reasoning model agent turns.
  Set `agents.defaults.commandTimeout: 300000` in openclaw.json.

### Patterns

- **Agent fallback chain** (Mac 9B primary): lmstudio-mac → gemini-3.1-pro-preview (429) →
  gemini-3-flash-preview (succeeds). Agents do work end-to-end even when LM Studio is slow.
- **Gemini free tier rate-limits fast** under repeated tests. Space out calls or use paid tier
  for production load. `google/gemini-3-flash-preview` is the working fallback for now.
- **ollama-win stub needed** in openclaw.json to suppress setup_macos.py warning.
  Added: `providers.ollama-win.baseUrl = http://192.168.254.103:11434`

### Full Matrix Results

| Agent          | Node | Model         | Status  | Time   | Notes                            |
|----------------|------|---------------|---------|--------|----------------------------------|
| win-researcher | Win  | qwen3.5-27b   | ✅ PASS | 130s   | empty text; reasoning_content ok |
| coder          | Win  | qwen3.5-27b   | ✅ PASS | 107s   | empty text; reasoning_content ok |
| autoresearcher | Win  | qwen3.5-27b   | ✅ PASS | 116s   | empty text; reasoning_content ok |
| main           | Mac  | qwen3.5-9b    | ✅ PASS | 308s   | fell back to gemini-3-flash      |
| mac-researcher | Mac  | qwen3.5-9b    | ✅ PASS | 105s   | fell back to gemini-3-flash      |
| orchestrator   | Mac  | qwen3.5-9b    | ✅ PASS | ~120s  | fell back to gemini-3-flash      |

---

## [2026-04-27] Perpetua-Tools git write-hang — root cause & workaround

**Symptom:** `git status`, `git diff --stat HEAD`, `git commit`, and `git update-ref`
all hang indefinitely (timeout at 10–20s) in the Perpetua-Tools working tree.
Fast read-only commands (`git log`, `git rev-parse`, `git diff --name-only HEAD -- <specific file>`)
work fine. Only commands that scan the full worktree or acquire a ref lock hang.

**Root cause (confirmed):** Repo has two active submodules (`vendor/ecc-tools`,
`packages/agentic-stack`) whose upstream URLs require network access. Git's submodule
status check inside `git status` attempts network probes that time out on any
submodule that isn't checked out cleanly. Combined with macOS filesystem event
watching (`git fsevents` daemon), write-locking operations stall waiting for event
confirmation that never arrives.

**Verified:** `git log` (pure read, no lock) returns instantly. `git write-tree`
(index snapshot, no ref lock) returns instantly. `git commit-tree` (object creation,
no ref lock) returns instantly. `git update-ref` (acquires `.git/refs/heads/main.lock`)
hangs at 5s. `git status --no-optional-locks --ignore-submodules=all` also hangs —
confirming the fsevents daemon, not submodule scanning, is the primary blocker.

**Workaround (used successfully):**
```bash
# 1. Stage specific files directly (bypasses full worktree scan)
git add docs/LESSONS.md .claude/skills/alphaclaw-session/SKILL.md

# 2. Create tree + commit object via plumbing (no ref lock needed)
TREE=$(git write-tree)
PARENT=$(git rev-parse HEAD)
COMMIT=$(GIT_AUTHOR_NAME="cyre" GIT_AUTHOR_EMAIL="Lawrence@cyre.me" \
  GIT_COMMITTER_NAME="cyre" GIT_COMMITTER_EMAIL="Lawrence@cyre.me" \
  git commit-tree "$TREE" -p "$PARENT" -m "commit message")

# 3. Advance branch ref via direct file write (bypasses git lock mechanism)
echo "$COMMIT" > .git/refs/heads/main

# 4. Push works normally (network op, not blocked)
GIT_TERMINAL_PROMPT=0 git push origin main
```

**Permanent fix options:**
- `git config core.fsmonitor false` in PT repo (disables fsevents polling)
- `git submodule deinit --force vendor/ecc-tools packages/agentic-stack` if submodules
  are not actively used
- VS Code "git.scanDelay" setting if using the VS Code git integration

**Status:** Direct-write workaround documented and working. Permanent fix not yet applied.
`Agent: Claude | 2026-04-27`

---

## [2026-04-27] Codex + Gemini dual code review — start.sh _print_banner()

Five bugs found and fixed across two review passes:

**Codex review (claude-code-reviewer subagent) found:**
1. `local win_ip="${WIN_IP:-?"}"` — malformed bash param expansion; `"` closed outer
   double-quote. Caused syntax error on `--status`/`--stop` paths. Fix: `"${WIN_IP:-?}"`
2. `$_` instead of `${_exit}` in discover.py fallback warning (line 203) — printed
   last shell arg, not exit code.
3. `&>/dev/null 2>&1` redundant double-redirect on all three `nc` probes.
4. `tier_color` declared but never used — commented as reserved for future ANSI.

**Gemini CLI review (v0.39.1) found:**
5. `nc` probes had no `-w` timeout flag — unreachable WIN_IP could hang startup
   for OS default (~30s). Fixed: added `-w 1` to all three probes.
6. Tier 3 label "CLOUD" was misleading — nc can't distinguish cloud-available from
   total network failure. Relabeled: "LOCAL DOWN · cloud fallback (check network)".

All fixes: `bash -n` passes. Three orama-system commits pushed: 86391c3, 128f7a6, 342edbc.
`Agent: Claude | 2026-04-27`

---

## [2026-04-27] Win Machine Hardware Spec (confirmed)

| Field | Value |
|-------|-------|
| Machine | DELL Precision Tower 3660 |
| RAM | 32 GB |
| GPU | NVIDIA RTX 3080 10GB VRAM |
| LM Studio | `192.168.254.103:1234` |
| CUDA constraint | ONE model at a time (RTX 3080 VRAM limit) |
| Active model | `qwen3.5-27b-claude-4.6-opus-reasoning-distilled-v2` (GGUF) |
| Secondary | `qwen3.5-9b-mlx` also loaded (but MLX won't run on CUDA; LM Studio falls back to CPU) |

**Important:** The Win 27B GGUF model responds in 107–130s per agent turn at full RTX 3080 capacity.
Do not load a second model on Win while a first is actively inferring.
`is_gpu_idle()` check is required before dispatching any new heavy Win agent task.

---

## [2026-04-27] thinkingLevel=off — Mac 9B Agents

**Problem:** Mac 9B MLX model generates large `<think>` blocks, extending agent turns to
100–308s. This is 5× slower than with thinking disabled (~15–25s expected).

**Solution (two-layer):**
1. **LM Studio UI** — toggle "Thinking Mode" off in the model settings panel.
   Must be done manually per LM Studio session; resets on restart.
2. **openclaw.json** (persistent) — set `thinkingLevel: "off"` and
   `modelParameters.budget_tokens: 0` per Mac agent:

```python
# Apply to all Mac agents in openclaw.json
import json, pathlib
cfg = json.loads(pathlib.Path.home().joinpath('.openclaw/openclaw.json').read_text())
for agent in cfg['agents']['list']:
    if agent.get('id') in ['main', 'mac-researcher', 'orchestrator']:
        agent['thinkingLevel'] = 'off'
        agent.setdefault('modelParameters', {})['budget_tokens'] = 0
pathlib.Path.home().joinpath('.openclaw/openclaw.json').write_text(
    json.dumps(cfg, indent=2, ensure_ascii=False))
```

**Status → AUTOMATED 2026-04-27.** `setup_macos.py` (step 3b) now enforces this on every
`start.sh` startup — no manual LM Studio toggle required.

**OpenClaw overwrite race (solved):** OpenClaw holds openclaw.json in memory and writes it
back on shutdown. Fix: `_restart_openclaw_if_running()` sends SIGTERM, waits for full exit,
then writes patched config — shutdown write completes first, our write wins.
Commit: `orama-system 3cba5bd`

**Win agents:** Leave thinking as-is. Win 27B always returns `reasoning_content`;
`text` field is often empty — agent reply parsers must check `reasoning_content` as fallback.
`Agent: Claude | 2026-04-27`

---

## [2026-04-27] Known AlphaClaw + OpenClaw working versions

- **AlphaClaw**: all versions 0.9.3 through **0.9.11** are confirmed working
- **OpenClaw**: all versions working (tested against AlphaClaw 0.9.3–0.9.11)
- `KNOWN_ALPHACLAW_VERSION` in setup_macos.py is set to `0.9.3` (minimum confirmed baseline)
  — patches are re-verified on version mismatch, so bumping this string is safe when a new
  version is confirmed working
`Agent: Claude | 2026-04-27`

---

## [2026-04-29] Win IP is dynamic — detect, never hardcode

**Problem:** Win LM Studio IP was hardcoded as `192.168.254.103` in SKILL.md and
referenced in openclaw.json. After a DHCP reassignment Win moved to `.105`, breaking
all Win agent dispatches.

**Root cause:** Two separate issues mixed into one symptom:
1. IP hardcoded in docs/skills instead of reading from openclaw.json
2. `discover.py` used `--force` flag for "always probe" — unintuitive for automation

**Fixes (automated, no manual steps required going forward):**

1. **discover.py default reversed:** Always probes on every call (no TTL skip by default).
   `--cached` flag is the new opt-in to use TTL-cached state. `--force` kept as no-op alias.
   ```bash
   python3 ~/.openclaw/scripts/discover.py          # always scans — finds new IP
   python3 ~/.openclaw/scripts/discover.py --cached # skip if < 5 min old
   ```

2. **SKILL.md updated:** Win IP row now reads "dynamic (auto-detected)" — no IP literal.
   Lookup pattern:
   ```python
   import json, pathlib
   cfg = json.loads(pathlib.Path.home().joinpath('.openclaw/openclaw.json').read_text())
   win_ip = cfg['models']['providers']['lmstudio-win']['baseUrl'].split('//')[1].split(':')[0]
   ```

3. **thinkingDefault fix:** OpenClaw schema rejected `thinkingLevel`/`modelParameters`.
   Correct field is `thinkingDefault: "off"` (enum, schema-valid). setup_macos.py step 3b
   now writes `thinkingDefault` and strips stale `thinkingLevel`/`modelParameters` on startup.

4. **gateway.js PATH fix (Patch G in setup_macos.py):** AlphaClaw spawned `openclaw gateway`
   with system PATH → Node v14 → "Node.js v22.12+ required" crash on every gateway start.
   Fix: `gatewayEnv()` prepends `path.dirname(process.execPath)` so child inherits Node v24.
   Applied idempotently by `step_patch_gateway()` on every `start.sh` run.

**Current state:** Win at `.105`, gateway live (`{"ok":true,"status":"live"}`), all 6 agents reachable.
`Agent: Claude | 2026-04-29`

---

## [2026-04-29] Git status hang — root cause was tracked node_modules (3818 files)

**Symptom:** `git status`, `git commit`, `git update-ref` hang indefinitely in PT.
For weeks we worked around it with git plumbing (`write-tree` → `commit-tree` →
direct `.git/refs/heads/main` write). This was treating the symptom, not the cause.

**Investigation (replicable diagnostic recipe):**

```bash
# 1. Check obvious culprits (all came back clean for PT)
git config --local --list | grep -E "fsmonitor|untracked|gpgsign"
ls -la .git/index.lock           # stale lock?
ls -la .git/hooks/               # hung pre-commit hooks?
pgrep -fl fsmonitor              # daemon?

# 2. Trace where git status is getting stuck
GIT_TRACE=1 GIT_TRACE_PERFORMANCE=1 timeout 6 git status 2>&1
# → trace ended at "preload-index.c:172 performance: …  preload index"
#   git was hanging in the SERIAL refresh phase that runs after preload

# 3. Confirm refresh is the hang
time timeout 5 git update-index --refresh   # → 30s timeout, never completes
time git ls-files                            # → 38ms (no stat)
time git write-tree                          # → 37ms (no stat)
# → smoking gun: lstat-each-tracked-file is what hangs

# 4. Bisect to find the bad path
for d in */; do
  start=$(date +%s)
  timeout 3 git status -uno -- "$d" >/dev/null 2>&1; rc=$?
  echo "$d: $(($(date +%s) - start))s exit=$rc"
done
# → packages/ exit=124 (hung), every other dir exit=0

# 5. Check tracked file count + symlinks
git ls-files | wc -l                         # → 3980
git ls-files | grep node_modules | wc -l     # → 3818 (96% of all tracked!)
git ls-files --stage | awk '$1=="120000"'    # → 6 tracked symlinks in node_modules
```

**Root cause:** `packages/alphaclaw-mcp/node_modules/` (3818 files including
6 cross-package symlinks) was committed by accident. Every `git status` had to
`lstat` all 3818 files. With APFS + macOS attribute lookups + symlink chains,
this exceeded any reasonable timeout.

**Fix (non-destructive, both repos preserved):**

```bash
# Add to .gitignore
echo "node_modules/" >> .gitignore
echo "**/node_modules/" >> .gitignore

# Untrack from index — --cached keeps files on disk
git rm -r --cached packages/alphaclaw-mcp/node_modules

# Commit normally (now ~140 files instead of 3980, status returns in <50ms)
git add .gitignore && git commit -m "chore: untrack node_modules (caused git status hang)"
```

**Universal rule (for the skill):** **`node_modules/` is never tracked.** Same
for `__pycache__/`, `.venv/`, `dist/`, `build/`, `target/`, `*.pyc` — anything
auto-generated by a package manager or compiler. The lockfile (`package-lock.json`,
`pnpm-lock.yaml`, `poetry.lock`, `Cargo.lock`) is the source of truth — that's
what gets committed. `npm install` (or equivalent) reproduces `node_modules/`
exactly from the lockfile.

**Why this matters beyond performance:**
1. `node_modules/` binaries are platform-specific (`darwin-arm64` won't run on Linux CI)
2. Inflates clone size (often 100MB+ per workspace)
3. Pollutes diffs (any `npm install` produces thousands of file changes)
4. Breaks `git status`/`git commit` performance once it crosses ~3k files on macOS

**For agents debugging future "git hangs":** the diagnostic recipe above takes
~2 minutes and reliably identifies the root cause. Start there before reaching
for plumbing workarounds. The plumbing workaround we used for weeks (write-tree
+ commit-tree + direct ref write) was the wrong layer to fix at — the index
itself was healthy; the working tree was the problem.

`Agent: Claude | 2026-04-29`
