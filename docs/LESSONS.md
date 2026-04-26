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

## [2026-04-22] Symlink Portability & Validation

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
