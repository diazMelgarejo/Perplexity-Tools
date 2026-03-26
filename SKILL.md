# SKILL.md — Perplexity-Tools Model Selection Skill

**Version:** `v0.9.4.3` (standardized from v0.9.0.0 onward) · **Updated:** 2026-03-26  
**Repo:** https://github.com/diazMelgarejo/Perplexity-Tools · **Branch:** `main`

**Layering (all interoperable and independently configurable):**

| Layer | Repo | Role |
|-------|------|------|
| **Orchestrator & instance manager** | **Perplexity-Tools** (this repo) | Top-level agent lifecycle, `ModelRegistry` / `config/*.yml`, FastAPI `/orchestrate`, idempotency |
| **Reasoning & routing methodology** | **ultrathink-system** | `single_agent/SKILL.md`, CIDF / process; multi-agent registry is **separately installable** and **not** required to run this orchestrator |
| **Subagent auto-selection (ECC-style)** | **ECC Tools** | Default subagent routing unless the top-level orchestrator overrides roles |
| **Karpathy AutoResearch sync** | [karpathy/autoresearch](https://github.com/karpathy/autoresearch) | Idempotent sync of the automated ML research loop; integrated via `/autoresearch/*` endpoints and `orchestrator/autoresearch_bridge.py` |

**Selection order:** Top-level model routing follows **this `SKILL.md` → `orchestrator/model_registry.py` + `config/models.yml` / `routing.yml`** first. Subagents use **ECC-tools** defaults unless overridden. **ultrathink-system** remains the methodology layer for reasoning execution, not a hard dependency of the YAML registry.

## Overview

This skill defines top-level model selection and routing logic for all agents
in the Perplexity-Tools orchestration system. It governs:

1. **Top-level agents** (Mac M2 + Dell RTX 3080): Follow **THIS file first**, then `ModelRegistry` / config (see `README.md`).
2. **Sub-agents**: Follow **ECC-tools default logic** (ECC-style auto-selection), then this file for overrides when the parent orchestrator assigns roles.
3. **Interoperability**: **Perplexity-Tools** is the top-level orchestrator; **ultrathink-system** provides reasoning methodology via its own `SKILL.md`; **ECC Tools** handles default subagent selection.
4. **Fallback chain**: Defined concretely in `config/routing.yml` and `config/models.yml` (local → shared → cloud by priority), not only the shorthand tree below.

---

## Hardware Profiles

### Profile A — MacBook Pro M2 (16GB Unified Memory)
```yaml
profile: mac_m2
default_model: qwen3:8b-instruct
fast_model: qwen3:4b-instruct
embedding_model: bge-m3
ollama_endpoint: http://localhost:11434
mlx_endpoint: http://localhost:1234  # LM Studio MLX alternative
vram_budget_gb: 10
use_cases:
  - standard_queries
  - synthesis
  - embeddings
  - quick_tasks
  - documentation
```

### Profile B — Dell Precision 3660 (RTX 3080 10GB VRAM)
```yaml
profile: dell_rtx3080
default_model: qwen3-coder:14b
fallback_model: qwen3:30b-a3b-instruct-q4_K_M
critic_model: qwen3:30b-a3b-instruct-q4_K_M
reranker_model: dengcao/qwen3-reranker-4b:Q5_K_M
ollama_endpoint: http://192.168.1.100:11434
mlx_endpoint: http://192.168.1.100:1234  # LM Studio alternative
vram_budget_gb: 10
use_cases:
  - code_generation
  - code_review
  - heavy_analysis
  - critic_pass
  - refinement
  - orchestration_fallback
```

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
    "max_tokens_per_call": 500,  # Keep prompts SHORT
    "estimated_cost_per_call": 0.05,
    "fallback": "qwen3:30b-a3b-instruct-q4_K_M"  # Dell local
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
    "fallback": "qwen3:30b-a3b-instruct-q4_K_M"  # Dell local, no real-time data
}
```

### Budget Guard
```python
BUDGET_GUARD = {
    "max_daily_spend_usd": 0.17,   # ~$5/month / 30 days
    "max_daily_calls": 5,
    "redis_tracking": True,
    "hard_cutoff": True,            # NEVER exceed, always fallback
    "fallback_on_exceed": "qwen3:30b-a3b-instruct-q4_K_M"
}
```

---

## Local Model Routing Decision Tree

```
Task Received
│
├─ Privacy Critical?
│  └─ YES → ALWAYS local, skip cloud
│      ├─ Code task → Dell: qwen3-coder:14b
│      └─ Standard → Mac: qwen3:8b-instruct
│
├─ Budget exhausted OR Internet offline?
│  └─ YES → Dell: qwen3:30b-a3b-instruct-q4_K_M (FALLBACK)
│
├─ Real-time data needed (< 7 days)?
│  └─ YES + Budget OK → Perplexity: grok-4.1-thinking
│
├─ Strategic reasoning (> 200 steps)?
│  └─ YES + Budget OK → Perplexity: claude-sonnet-4.5-thinking
│
├─ Heavy code generation (> 500 lines)?
│  ├─ > 2000 lines → Dell: qwen3:30b-a3b-instruct-q4_K_M
│  └─ 500-2000 lines → Dell: qwen3-coder:14b
│
├─ Quick/interactive task?
│  └─ Mac: qwen3:4b-instruct (fastest)
│
└─ Default → Mac: qwen3:8b-instruct
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
  - qwen3:8b-instruct    # primary
  - qwen3:4b-instruct    # autocomplete
  - bge-m3               # embeddings
cloud_enabled: true      # via Perplexity API
critc_pass: false        # No Dell available
note: Reduced capability, no critic pass
```

### Mode 2: Dell Only (Standalone)
```yaml
mode: dell_only
active_models:
  - qwen3-coder:14b                    # primary coding
  - qwen3:30b-a3b-instruct-q4_K_M     # critic + fallback
  - dengcao/qwen3-reranker-4b:Q5_K_M  # reranking
cloud_enabled: true
critic_pass: true
```

### Mode 3: Mac + Dell LAN (Full Orchestration — RECOMMENDED)
```yaml
mode: lan_full
mac_endpoint: http://192.168.1.101:11434
dell_endpoint: http://192.168.1.100:11434
redis_broker: http://192.168.1.100:6379
cloud_enabled: true
critic_pass: true
fallback_chain:
  - cloud_perplexity
  - dell_qwen3_30b
  - dell_qwen3_14b
  - mac_qwen3_8b
```

### Mode 4: LM Studio MLX (Alternative Backend)
```yaml
mode: lm_studio_mlx
mac_mlx_endpoint: http://localhost:1234
dell_mlx_endpoint: http://192.168.1.100:1234
note: Use when Ollama unavailable; same model routing logic applies
mlx_models:
  mac: mlx-community/Qwen3-8B-4bit
  dell_coding: mlx-community/Qwen3-14B-4bit
  dell_critic: mlx-community/Qwen3-30B-4bit
```

---

## Idempotent Orchestrator Rules

This repo (**Perplexity-Tools**) is the **top-level orchestrator and instance manager**:

1. **Check before creating**: Before spawning a new top-level agent, consult persisted state (`.state/agents.json` via `AgentTracker`) **and** the `POST /orchestrate` idempotency check (`task_type` + task content hash). Strategy docs may also use Redis/Postgres in larger deployments; the reference runtime in this branch uses **file-backed** tracking first.
2. **Reuse existing**: If a matching **running** agent exists for the same role and task hash → **do not** silently duplicate; return a **conflict** and **ask the user** whether to proceed (API: `force=true` only after explicit user approval).
3. **Conflict resolution**: Duplicate-role conflicts → `GET /agents/conflicts` or human review; **ask the user** before overriding idempotency.
4. **Destroy on completion**: Remove or mark agents stopped when tasks complete; optional `DELETE /agents/gc/stopped`.
5. **State persistence**: Default: `.state/agents.json` (and `.state/budget.json` for `CostGuard`). Add Redis/Postgres for distributed coordination when you wire the full strategy stack.

```python
IDEMPOTENT_RULES = {
    "check_registry_before_spawn": True,   # AgentTracker + /orchestrate task_hash
    "reuse_existing_agents": True,
    "ask_user_when_matching_running_agent": True,  # conflict response unless force=true
    "auto_destroy_on_complete": True,
    "state_store_default": ".state/agents.json",
}
```

---

## autoresearch Tasks

When `task_type == "autoresearch"` or `"ml-experiment"`:

1. **FIRST**: Call `POST /autoresearch/sync?run_tag=mar22` (or current date tag) → abort if `sync_ok == false`.
2. **THEN**: Route top-level model via `ModelRegistry.route_task("strategy")` → picks Claude or Qwen3-30B per budget.
3. **SPAWN**:
   - One **Coder** agent (`role=autoresearch-coder`, `device=win-rtx3080`) — edits `train.py`, deploys via `autoresearch_bridge.deploy_train_py()`, runs via `run_experiment_on_gpu()`.
   - One **Evaluator** agent (`role=autoresearch-evaluator`, `device=mac`) — reads `log.txt` via `fetch_run_log()`, parses `val_bpb`, writes to `swarm_state.md`.
   - One **Orchestrator** agent (`role=autoresearch-orchestrator`, `device=mac`) — reads `swarm_state.md` + `git log`, proposes next hypothesis.
4. **IDEMPOTENCY**: Before spawning any agent, call `AgentTracker.find_existing(role, task_hash)`.
   - If found → ask user before creating another.
   - If not found → register and proceed.
5. **GPU LOCK**: `swarm_state.md` **Status: IDLE / BUSY** is the only synchronization primitive.
   - Only the **Coder** agent may flip `IDLE → BUSY` before dispatching a run.
   - Only the **Coder** agent may flip `BUSY → IDLE` after `fetch_run_log()` completes.
6. **NEVER** route autoresearch tasks to cloud models without explicit `--override-cloud` flag.

Local autoresearch clone: keep private env in a gitignored file; document machine-specific paths in `~/autoresearch/LOCAL_SETUP.md` (create locally, not committed).

ECC install example for parallel subagent swarms (per main swarm):  
`ecc-install --skills coding-standards,configure-ecc,continuous-learning,continuous-learning-v2,deep-research,eval-harness,exa-search,iterative-retrieval,market-research,plan,search-first,strategic-compact,verification-loop,verify`

---

## Interoperability

| Repo | Role | Interface |
|------|------|-----------|
| **Perplexity-Tools** (this) | Top-level orchestrator & instance manager | `python -m orchestrator.fastapi_app` → `/orchestrate`, `/health`, `/models`, `/agents` |
| **ultrathink-system** | Reasoning methodology; `single_agent/SKILL.md`; multi-agent registry optional | Skill / HTTP per that repo — **independently configurable** |
| **ECC-tools** | Sub-agent ECC-style auto-selection | Default logic for sub-agents unless overridden |

### Cross-repo calls:
```python
# Call ultrathink-system for deep reasoning
ultrathink_endpoint = "http://localhost:8001/ultrathink"

# Delegate sub-agent selection to ECC-tools
ecc_tools_endpoint = "http://localhost:8002/select-model"
```

---

## AutoResearch Integration (Karpathy ML Loop)

**Repo**: [https://github.com/karpathy/autoresearch](https://github.com/karpathy/autoresearch)  
**Bridge Module**: `orchestrator/autoresearch_bridge.py`  
**Routing**: `config/routing.yml` (autoresearch routes, e.g. `autoresearch`, `ml-experiment`, `autoresearch-coder`, …)  
**Models**: `config/models.yml` (e.g. `qwen3-coder-14b`, `qwen3-30b-autoresearch-critic`, plus shared defaults)

### Purpose

Perplexity-Tools can drive an **idempotent sync** of Karpathy’s AutoResearch-style loop for automated ML research workflows:

1. **Remote GPU execution** (e.g. Windows RTX 3080) from a Mac controller
2. **Automated experiment loop** (program → training script → iterative edits → metrics)
3. **ECC Tools Stage 4**-style executor selection for parallel coding subagents (see `.claude/ecc-tools.json` in your environment)

### Architecture

```
User/Orchestrator
      ↓
POST /autoresearch/sync  →  preflight / bootstrap
      ↓
orchestrator/autoresearch_bridge.py
      ↓
[Mac: prepare artifacts] → [scp to Windows] → [Windows: python train.py]
      ↓
Feedback loop: metrics → code edits → retrain (idempotent via run tracking)
```

### FastAPI Endpoints (representative)

| Method | Path | Notes |
|--------|------|--------|
| `POST` | `/autoresearch/sync` | Git sync + preflight; query `run_tag` optional |
| `GET` | `/autoresearch/gpu_status` | Reads `swarm_state.md` GPU lock |

Additional endpoints (`/autoresearch/start`, `/status/{run_id}`, …) may be added in `autoresearch_bridge` as the integration matures; align with `fastapi_app.py`.

### Key Models (typical)

| Task | Model | Device | Rationale |
|------|-------|--------|-----------|
| Code generation | `qwen3-coder-14b` (or `qwen3-coder:14b` on Ollama) | Windows RTX 3080 | Primary coder for `train.py` edits |
| Critic / evaluator | `qwen3-30b-autoresearch-critic` | Windows (shared Ollama) | Review + orchestration support |
| Light coordination | local Qwen3 8B / MLX | Mac | Optional lightweight loop steps |

### Idempotency Contract

```python
AUTORESEARCH_IDEMPOTENCY = {
    "run_id_format": "nanoid or uuid",  # Unique per experiment
    "state_file": ".state/autoresearch_runs.json",  # if implemented by bridge
    "duplicate_check": "program.md hash + model + hyperparams",
    "reuse_existing": True,
    "force_new": False,  # force=true to override duplicate check
}
```

### LAN Setup (Mac ↔ Windows)

- **SSH key auth** only; scope `sshd` to LAN if possible.
- Secrets: **session exports** or a **gitignored** `.env` — do not commit keys.
- **File transfer**: prefer **`scp`** (rsync not guaranteed on Windows OpenSSH).

### Integration with ECC Tools (Stage 4 parallel executors)

Optional parallel executors (up to 5) via ECC configuration — see `vendor/ecc-tools/` after `POST /ecc/sync` and local `.claude/ecc-tools.json`.

Layering:

1. **Perplexity-Tools** — orchestrator + `/autoresearch/*`
2. **ultrathink-system** — CIDF / multi-step planning
3. **ECC Tools** — subagent / executor selection
4. **Karpathy AutoResearch** — experiment execution on GPU

### Notes

- `program.md` should use **explicit** host/path values where required (avoid unresolved shell variables in markdown).
- **prepare** / heavy data prep runs on the **GPU runner** when that’s the contract.
- **Never** route autoresearch to cloud models without an explicit override flag (see **autoresearch Tasks** above).

---

## ECC Tools Runtime Sync

**Module**: `orchestrator/ecc_tools_sync.py`  
**Vendor Dir**: `vendor/ecc-tools/` (gitignored; populated at startup or via `POST /ecc/sync`)  
**State File**: `.state/ecc_sync.json`  
**Source Repo**: [affaan-m/everything-claude-code](https://github.com/affaan-m/everything-claude-code)

### How It Works

At FastAPI startup (and on demand):

1. **Clone or pull** `everything-claude-code` into `vendor/ecc-tools/` (shallow clone on first run).
2. **Read** `vendor/ecc-tools/.claude/ecc-tools.json` for `managedFiles` when present.
3. **Hash-gated copy**: SHA-256 compare source vs destination; copy only when content differs (unless `force=true`).
4. **Persist** commit hash and per-file hashes in `.state/ecc_sync.json`.
5. **Fast path**: if upstream commit unchanged since last sync, skip redundant copies (`status: up_to_date`).

### API

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/ecc/status` | Last sync metadata (no network) |
| `POST` | `/ecc/sync?force=false` | Run sync; `force=true` recopies all managed files |

Managed paths and destinations are defined in `DESTINATION_OVERRIDES` inside `ecc_tools_sync.py` (skills, `.codex/`, `.claude/identity.json`, `ecc-tools.json`, etc.).

---

## Installation

```bash
# 1. Pull required Ollama models
ollama pull qwen3:8b-instruct          # Mac primary
ollama pull qwen3:4b-instruct          # Mac fast
ollama pull qwen3-coder:14b            # Dell coding
ollama pull qwen3:30b-a3b-instruct-q4_K_M  # Dell critic/fallback (KEY MODEL)
ollama pull bge-m3                     # Embeddings
ollama pull dengcao/qwen3-reranker-4b:Q5_K_M  # Reranker

# 2. Install Python dependencies
pip install crewai==1.9.0 perplexity-ai loguru redis fastapi uvicorn python-dotenv httpx

# 3. Configure environment
cp .env.example .env
# Edit: PERPLEXITY_API_KEY, REDIS_HOST, MAC_ENDPOINT, DELL_ENDPOINT

# 4. Start orchestrator
python orchestrator.py
```

---

## Changelog

### v0.9.1.0 (2026-03-22)
- Added SKILL.md with complete model selection logic
- Added Qwen3-30B-A3B as critic, refiner, and offline fallback
- Added Perplexity API integration (Claude Sonnet 4.5 + Grok 4.1)
- Added idempotent orchestrator rules
- Added 4 runtime modes (Mac-only, Dell-only, LAN-full, LM-Studio-MLX)
- Added budget guard ($5/month hard cap)
- Integrated with ultrathink-system and ECC-tools

### v0.9.4.1 (autoresearch + ECC sync)
- Documented **autoresearch Tasks**, **AutoResearch Integration**, and **ECC Tools Runtime Sync** in `SKILL.md`
- Added `orchestrator/ecc_tools_sync.py`, `GET /ecc/status`, `POST /ecc/sync`, startup sync via FastAPI lifespan
- Added `docs/ULTRATHINK_v0.9.4.0_SKILL_autoresearch_subsection.md` for paste into ultrathink-system `v0.9.4.0`


---

## ultrathink-system Integration

**When routing to ultrathink-system, the following rules govern PT behavior.**

### When PT Calls ultrathink

ultrathink-system is invoked via `config/routing.yml` routes `deep_reasoning` and `code_analysis` when:
- `task_type` is `deep_reasoning` (complex multi-step reasoning, privacy-critical tasks)
- `task_type` is `code_analysis` (deep code analysis requiring extended reasoning)
- `privacy_critical=True` is set in the task payload
- `reasoning_depth=ultra` is explicitly requested by user

### PT Behavior When Calling ultrathink

| Rule | Detail |
|---|---|
| PT runs first | PT model selection always executes before calling ultrathink |
| Stateful dedup | PT checks `.state/agents.json` before calling ultrathink (ultrathink is stateless) |
| Endpoint | `${ULTRATHINK_ENDPOINT}` (default: `http://localhost:8001/ultrathink`) |
| Timeout | `${ULTRATHINK_TIMEOUT}` seconds (default: 120) |
| Fallback | If `ULTRATHINK_ENABLED=false` or endpoint unreachable, use local qwen3:30b |
| Privacy | ultrathink stays local — no cloud calls from Layer 2 downward |

### Integration References

- ultrathink SKILL.md: `https://github.com/diazMelgarejo/ultrathink-system/blob/main/single_agent/SKILL.md`
- Bridge spec: `https://github.com/diazMelgarejo/ultrathink-system/blob/main/docs/PERPLEXITY_BRIDGE.md`
- Routing config: `config/routing.yml` (deep_reasoning + code_analysis routes)
- Health check: `./check-stack.sh` (in ultrathink-system repo)
