# SKILL.md — Perplexity-Tools Model Selection Skill

**Version:** `v0.9.9.6` · **Updated:** 2026-04-08
**Repo:** https://github.com/diazMelgarejo/Perplexity-Tools · **Branch:** `main`

**Layering (all interoperable and independently configurable):**

| Layer | Repo | Role |
|-------|------|------|
| **Orchestrator & instance manager** | **Perplexity-Tools** (this repo) | Top-level agent lifecycle, `ModelRegistry` / `config/*.yml`, FastAPI `/orchestrate`, idempotency |
| **Reasoning & routing methodology** | **ultrathink-system** | `bin/skills/SKILL.md`, AFRP (pre-router gate) / CIDF / process; multi-agent registry is **separately installable** and **not** required to run this orchestrator |
| **Subagent auto-selection (ECC-style)** | **ECC Tools** | Default subagent routing unless the top-level orchestrator overrides roles |
| **Karpathy AutoResearch sync** | [uditgoenka/autoresearch](https://github.com/uditgoenka/autoresearch) | Idempotent sync of the automated ML research loop; integrated via `/autoresearch/*` endpoints and `orchestrator/autoresearch_bridge.py` |

**Selection order:** Top-level model routing follows **this `SKILL.md` → `orchestrator/model_registry.py` + `config/models.yml` / `routing.yml`** first. Subagents use **ECC-tools** defaults unless overridden. **ultrathink-system** remains the methodology layer for reasoning execution, not a hard dependency of the YAML registry.

---

## State Ownership & Redis Strategy

> **Canonical MVP wording:** For MVP/v1.0, ultrathink remains stateless and has no Redis requirement. PT is the sole orchestration layer and owns agent instantiation, tracking, queueing, budget enforcement, and file-based runtime state. Redis-backed coordination is a future PT-only enhancement planned for multi-instance distributed deployments in v1.1 and above.

**Rules:**
- Single PT instance or LAN MVP per machine: file-based state only (`.state/agents.json`, `.state/budget.json`)
- No Redis mentions in ultrathink install/runtime requirements
- Any future queue/cache/distributed lock support belongs to PT
- Redis only activates when PT supports multi-instance distributed operation (v1.1+), not before

---

## Multi-Computer Orchestration (Hardware-Aware)

This orchestrator is designed for **full hardware profile awareness** [web:40] across a distributed LAN environment. It adapts standard multi-agent orchestration strategies [web:23][web:25] (sequential, concurrent, routing) to physical hardware constraints.

### LAN Resume & Distributed Discovery
- **Automatic Resume (LAN Detect)**: On startup, the system scans the LAN for existing instances (Redis: `agent:registry:*` or local `.state/agents.json`).
- **Session Continuity**: Resume from the last known state by re-attaching to running agent processes or resuming from the **Short Persistence Log** (`.state/session.log`).
- **Discovery Strategy**: Attempt to connect to `REDIS_HOST`. If unreachable, fallback to the local state file for standalone operations.

### Spawn Reconciliation (Pre-Model Spawning)
- **Centralized Registry Check**: Before spawning any agent, the orchestrator MUST check the `AgentTracker` (global registry) for an existing agent with the same `role` and `task_hash`.
- **Proper Session Planning**: Reconcile spawns *before* model assignment to prevent dual-task GPU contention or redundant model loading.
- **Model Assignment**: Once a spawn is reconciled, assign the model based on the hardware profile's VRAM/RAM ceiling (see [hardware/SKILL.md](https://github.com/diazMelgarejo/Perplexity-Tools/blob/main/hardware/SKILL.md)).

### Profile Deployment Logic
| Profile ID | Architecture | Core Specialization | Primary Use Case |
|---|---|---|---|
| `mac-studio` | Apple Silicon | Low-latency, Large RAM | Orchestration, Synthesis, Multi-step reasoning |
| `win-rtx3080` | x86-64 / CUDA | Parallel GPU compute | Heavy coding, Critic passes, ML experiments |

---

## Hardware Profiles (Summary)
Refer to [hardware/SKILL.md](https://github.com/diazMelgarejo/Perplexity-Tools/blob/main/hardware/SKILL.md) for full specs.

### Profile A — mac-studio (16GB+ Unified Memory)
- **Primary**: `glm-5.1:cloud` via local Ollama when the live probe succeeds
- **Primary**: `Qwen3.5-9B-MLX-4bit` (LM Studio, Metal full offload, context 4096)
- **Roles**: Thin Orchestrator via GLM, local verifier/orchestrator fallback via Mac LM Studio.
- **VRAM**: N/A (Unified). LM Studio handles MLX weights natively.

### Profile B — win-rtx3080 (10GB VRAM)
- **Primary**: `Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2` (LM Studio, gpu_offload=40)
- **Roles**: Coder, Checker, Refiner, Executor, Verifier, AutoResearch Coder.
- **Constraints**: gpu_offload=40 layers; `context 16384`; fallback: `qwen3-coder:14b`, other reachable LM Studio models, then backup Ollama `qwen3.5:35b-a3b-q4_K_M`.

---

## Cloud Routing Rules (< $5/month budget)

### Priority 1 — Orchestration (Claude Sonnet 4.5 Thinking via Perplexity)
```python
CLOUD_ORCHESTRATION = {
    "provider": "perplexity",
    "model": "anthropic/claude-sonnet-4.5-thinking",
    "trigger_conditions": [
        "strategic_decision == True",
        "reasoning_steps > 200",
        "multi_repo_coordination == True"
    ],
    "max_calls_per_day": 3,
    "max_tokens_per_call": 500, # Keep prompts SHORT
    "estimated_cost_per_call": 0.05,
    "fallback": "qwen3-30b-critic" # Dell local
}
```

### Priority 2 — Finance & Real-Time Research (Grok 4.1 Thinking via Perplexity)
```python
CLOUD_RESEARCH = {
    "provider": "perplexity",
    "model": "xai/grok-4.1-thinking",
    "trigger_conditions": [
        "requires_recent_info == True",
        "is_finance_realtime == True",
        "query_date_range < 7_days"
    ],
    "max_calls_per_day": 2,
    "max_tokens_per_call": 1500,
    "estimated_cost_per_call": 0.03,
    "fallback": "qwen3-30b-critic" # Dell local, no real-time data
}
```

### Budget Guard
```python
BUDGET_GUARD = {
    "max_daily_spend_usd": 0.17, # ~$5/month / 30 days
    "max_daily_calls": 5,
    "redis_tracking": True,
    "hard_cutoff": True, # NEVER exceed, always fallback
    "fallback_on_exceed": "qwen3-30b-critic"
}
```

---

## Local Model Routing Decision Tree

```
Task Received
│
├─ Privacy Critical?
│  └─ YES → ALWAYS local, skip cloud
│     ├─ Code task → win-rtx3080: Qwen3.5-27B (LM Studio) → qwen3-coder:14b → local LM Studio fallbacks
│     └─ Standard → mac-studio: glm-5.1:cloud probe → Qwen3.5-9B-MLX-4bit if GLM unavailable
│
├─ Budget exhausted OR Internet offline?
│  └─ YES → win-rtx3080: qwen3-30b-critic (FALLBACK)
│
├─ Real-time data needed (< 7 days)?
│  └─ YES + Budget OK → Perplexity: grok-4.1-thinking
│
├─ Strategic reasoning (> 200 steps)?
│  └─ YES + Budget OK → Perplexity: claude-sonnet-4.5-thinking
│
├─ Heavy code generation (> 500 lines)?
│  ├─ > 2000 lines → win-rtx3080: Qwen3.5-27B (LM Studio, context 16384)
│  └─ 500-2000 lines → win-rtx3080: Qwen3.5-27B (LM Studio)
│
├─ Quick/interactive task?
│  └─ mac-studio: glm-5.1:cloud if reachable, else Qwen3.5-9B-MLX-4bit
│
└─ Default → mac-studio: Qwen3.5-9B-MLX-4bit (LM Studio, context 4096)
```

---

## Critic & Refinement Pass (Qwen3-30B)
The `qwen3:30b-a3b-instruct-q4_K_M` model on Dell serves as:
1. **Default Offline Fallback** — Replaces any cloud model when unreachable
2. **Local Critic** — Reviews batch agent outputs for quality (score 1-10)
3. **Refiner** — Improves sub-agent outputs before synthesis
4. **Orchestration Fallback** — Decomposes tasks when Claude is unavailable

```python
CRITIC_CONFIG = {
    "model": "qwen3:30b-a3b-instruct-q4_K_M",
    "endpoint": "http://192.168.1.100:11434",
    "temperature": 0.6,
    "max_tokens": 8192,
    "critic_prompt_template": """
    Review these results for quality, accuracy, completeness:
    {results}
    Provide:
    1. Quality score (1-10)
    2. Issues found
    3. Recommended improvements
    4. Verdict: APPROVE or NEEDS_REVISION
    """,
    "trigger": "always_after_batch_if_subtasks > 1"
}
```

---

## Runtime Modes

### Mode 1: Mac Only (Standalone)
```yaml
mode: mac_only
active_models:
  - qwen3.5-9b-mlx-4bit # primary
  - qwen3-8b-instruct # fallback
cloud_enabled: true # via Perplexity API
critic_pass: false # No Dell available
note: Reduced capability, no critic pass
```

### Mode 2: Dell Only (Standalone)
```yaml
mode: dell_only
active_models:
  - qwen3.5-35b-a3b-q4 # primary coding
  - qwen3-30b-critic # critic + fallback
cloud_enabled: true
critic_pass: true
```

### Mode 3: Mac + Win LAN (Full Orchestration — RECOMMENDED)
```yaml
mode: lan_full
# LM Studio endpoints (canonical — v0.9.9.6)
lmstudio_mac: http://192.168.254.103:1234    # Qwen3.5-9B-MLX-4bit, verifier/orchestrator fallback
lmstudio_win: http://192.168.254.100:1234    # Qwen3.5-27B, gpu_offload=40, context 16384
# Portal dashboard
portal: http://192.168.254.103:8002          # LAN status (auto-refresh 10s)
# Ollama lanes
ollama_mac: http://192.168.254.103:11434     # glm-5.1:cloud local client
ollama_win: http://192.168.254.100:11434     # qwen3-coder:14b / critic / backup
cloud_enabled: true
critic_pass: true
fallback_chain:
  - ollama_mac_glm         # thin orchestrator when glm-5.1:cloud probe succeeds
  - lmstudio_win           # primary heavy coder / autoresearch executor
  - lmstudio_mac           # orchestrator + validator fallback
  - ollama_win             # qwen3-coder:14b, qwen3-30b critic, qwen3.5:35b backup
  - ollama_mac
  - cloud_perplexity       # cost_guard checked first
```

---

## Idempotent Orchestrator Rules
This repo (**Perplexity-Tools**) is the **top-level orchestrator and instance manager**:
1. **Check before creating**: Consult `.state/agents.json` via `AgentTracker`.
2. **Reuse existing**: Return conflict if matching running agent exists (override with `force=true`).
3. **Conflict resolution**: Ask user before overriding idempotency.
4. **Destroy on completion**: Mark agents stopped when tasks complete.

---

## Multi-Agent Collaboration Protocol

> Encode these rules in every agent's SOUL.md and session start. They prevent the most common
> conflicts when multiple AI agents work on the same codebase simultaneously.

### Pre-Session (before touching any file)
```bash
git fetch origin main
git log --oneline origin/main..HEAD   # uncommitted work ahead of main
git log --oneline HEAD..origin/main   # commits by other agents since we branched
```
If another agent pushed recently to files you plan to touch, pull first.

### Scope Claim (first write to LESSONS.md)
Append an `[IN PROGRESS]` marker before starting work:
```
## [IN PROGRESS] YYYY-MM-DD — Claude — <topic>
Files: <file1>, <file2>
```
Replace with a proper dated header when done. This is the lightweight coordination signal.

### IP and Endpoint Defaults Rule
- **Production code defaults**: always `127.0.0.1` (loopback) — never a real LAN IP
- **Real LAN IPs**: live only in `.env` files (gitignored), loaded via `os.getenv()`
- **Tests**: validate the loopback default; never assert a hardcoded LAN IP
- LAN IPs that slip into source defaults will break CI on every machine that isn't yours

### Version Bump Registry
When bumping version, update ALL of these — no partial bumps:

| File | Field |
|------|-------|
| `pyproject.toml` | `version` |
| `orchestrator/__init__.py` | `__version__` |
| `orchestrator/fastapi_app.py` (×2) | app metadata + `/health` response |
| `orchestrator.py` | `VERSION` |
| `config/devices.yml` | `version` |
| `config/models.yml` | `version` |
| `SKILL.md` | frontmatter `**Version:**` + Changelog entry |
| `hardware/SKILL.md` | `Version:` header |
| `README.md` | title + metadata table |

**Current version: `v0.9.9.6`** — do not bump until explicitly instructed.

### Commit Message Contract (for agent-to-agent communication)
Every commit body should include:
- Which **constants / env vars / function signatures** changed
- Which **files other agents must re-read** before making assumptions
- Whether any **test baselines changed** (e.g., new expected defaults)

This is the primary async communication channel between agents that never share a session.

### Conflict Recovery Playbook
| Symptom | Cause | Fix |
|---------|-------|-----|
| `stash pop` add/add on every file | Another agent pushed to your files while you were working | `git checkout --theirs <file>` for yours, patch manually |
| `rebase` produces add/add on ALL files | Branch has no common ancestor with main | `git reset --hard origin/main`, re-apply your files manually |
| File appears duplicated / concatenated | Both versions of a conflict were appended | Python line-by-line surgery: keep only `lines[N:]` for the good half |
| CI fails with `192.168.x.x` in assertion | LAN IP leaked into a source default | Replace with `127.0.0.1` in the source, not the test |
| Module constant test contamination | `importlib.reload()` left stale env state | Add `autouse` fixture that reloads before AND after |

---

## Changelog

### v0.9.9.6 (2026-04-08)
- **Gateway lifecycle ownership**: setup-time AlphaClaw flow now delegates to the canonical bootstrap script first, while preserving local fallback behavior.
- **Perplexity onboarding**: the smoke-test path can force one-time key validation without weakening the richer singleton client flow.
- **Client ergonomics**: `PerplexityClient.get()` now accepts optional `base_url` and `timeout` overrides for alternate endpoints and test harnesses.
- **Docs/examples**: README and smoke-test usage now show the preferred `stream()` path plus the new client/config flags.
- **Version alignment**: runtime, package, and skill surfaces are synchronized to `v0.9.9.6`.

### v0.9.9.1 (2026-04-04)
- **LM Studio promoted to primary backend**: Win=Qwen3.5-27B (gpu_offload=40, context 16384); Mac=Qwen3.5-9B-MLX-4bit (context 4096 conservative)
- **Mac roles updated**: orchestrator, final-validator, presenter, top-level
- **Win roles updated**: coder, checker, refiner, executor, verifier (UltraThink agent)
- **Mode 3 LAN config**: LM Studio endpoints (port 1234) + portal (port 8002) documented
- **Routing tree**: all model references updated to LM Studio canonical IDs
- **Enforcement**: `scripts/check_docs_sync.py` + `.pre-commit-config.yaml` added [SYNC]

### v0.9.9.0 (2026-03-30)
- **Version freeze**: all files synchronized to 0.9.9.0, held until 1.0 RC
- **v1.1+ Roadmap**: Deferred MCP-first transport documented in both repos
- **Bridge tests**: `tests/test_ultrathink_bridge.py` — unit tests for HTTP bridge module
- **HTTP bridge always-active**: Removed `ULTRATHINK_HTTP_BACKUP_ENABLED` opt-in flag [SYNC]
- **Renamed**: `ultrathink_http_backup` → `ultrathink_bridge` across all code and response keys

### v0.9.7.0 (2026-03-28)
- **AFRP cross-reference**: ultrathink-system layer now documents AFRP (pre-router gate) in 4-layer architecture table [SYNC]
- **Fixes**: orchestrator.py syntax errors, confidential folder references removed, FastAPI version aligned
- **Sync**: Both repos synchronized to v0.9.7.0 [SYNC]

### v0.9.6.0 (2026-03-27)
- **LAN Continuity**: Implemented **LAN Detect & Resume** for seamless multi-computer operation.
- **Orchestration**: Full hardware profile awareness implemented [web:40].
- **Pre-Flight Reconciliation**: Added spawn detection and reconciliation *before* model spawning for efficiency.
- **Logging**: Added **Short Persistence Log** (`.state/session.log`) for low-overhead session tracking.
- **Strategies**: Adapted durable workflow and intelligent routing for multi-computer LAN.
- **Models**: Updated primaries to Qwen 3.5 series (9B MLX on Mac, 35B MoE on Dell).
- **Hardening**: Reinforced VRAM safety rules and hardware-bound routing.

### v0.9.1.0 (2026-03-22)
- Added SKILL.md with complete model selection logic
- Added Qwen3-30B-A3B as critic, refiner, and offline fallback
- Added Perplexity API integration (Claude Sonnet 4.5 + Grok 4.1)
- Added 4 runtime modes (Mac-only, Dell-only, LAN-full, LM-Studio-MLX)
- Integrated with ultrathink-system and ECC-tools
