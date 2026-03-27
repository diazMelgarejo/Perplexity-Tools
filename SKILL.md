# SKILL.md — Perplexity-Tools Model Selection Skill

**Version:** `v0.9.6.0` (standardized from v0.9.0.0 onward) · **Updated:** 2026-03-27
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

This skill defines top-level model selection and routing logic for all agents in the Perplexity-Tools orchestration system. It governs:

1. **Top-level agents** (Mac M2 + Dell RTX 3080): Follow **THIS file first**, then `ModelRegistry` / config (see `README.md`).
2. **Sub-agents**: Follow **ECC-tools default logic** (ECC-style auto-selection), then this file for overrides when the parent orchestrator assigns roles.
3. **Interoperability**: **Perplexity-Tools** is the top-level orchestrator; **ultrathink-system** provides reasoning methodology via its own `SKILL.md`; **ECC Tools** handles default subagent selection.
4. **Fallback chain**: Defined concretely in `config/routing.yml` and `config/models.yml` (local → shared → cloud by priority), not only the shorthand tree below.

---

## Multi-Computer Orchestration (Hardware-Aware)

This orchestrator is designed for **full hardware profile awareness** [web:40] across a distributed LAN environment. It adapts standard multi-agent orchestration strategies [web:23][web:25] (sequential, concurrent, routing) to physical hardware constraints.

### Hardware Strategy Adaptation
- **Durable Workflow Architecture**: Multi-agent sessions are persistent across reloads via `.state/agents.json`.
- **Intelligent Routing (Hardware-Bound)**: Instead of routing by cost alone, the orchestrator routes by **VRAM/RAM availability** [web:40] and **compute specialization**.
- **Role-Based Provisioning**: Agents are dynamically assigned to the hardware profile that best matches their role's compute profile.

### Profile Deployment Logic
| Profile ID | Architecture | Core Specialization | Primary Use Case |
|---|---|---|---|
| `mac-studio` | Apple Silicon | Low-latency, Large RAM | Orchestration, Synthesis, Multi-step reasoning |
| `win-rtx3080` | x86-64 / CUDA | Parallel GPU compute | Heavy coding, Critic passes, ML experiments |

---

## Hardware Profiles (Summary)
Refer to [hardware/SKILL.md](https://github.com/diazMelgarejo/Perplexity-Tools/blob/main/hardware/SKILL.md) for full specs.

### Profile A — mac-studio (16GB+ Unified Memory)
- **Primary**: `qwen3.5-9b-mlx-4bit` (MLX)
- **Roles**: Orchestrator, Manager, General, Synthesis.
- **VRAM**: N/A (Unified).

### Profile B — win-rtx3080 (10GB VRAM)
- **Primary**: `qwen3.5-35b-a3b-q4` (Ollama)
- **Roles**: Coding, Autoresearch, Heavy Reasoning, Critic.
- **Constraints**: 10GB hard ceiling; `num_ctx <= 8192`.

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
│     ├─ Code task → win-rtx3080: qwen3.5-35b-a3b-q4
│     └─ Standard → mac-studio: qwen3.5-9b-mlx-4bit
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
│  ├─ > 2000 lines → win-rtx3080: qwen3-30b-critic
│  └─ 500-2000 lines → win-rtx3080: qwen3.5-35b-a3b-q4
│
├─ Quick/interactive task?
│  └─ mac-studio: qwen3-8b-instruct (fastest)
│
└─ Default → mac-studio: qwen3.5-9b-mlx-4bit
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
  - dell_qwen3_35b
  - mac_qwen3_9b
```

---

## Idempotent Orchestrator Rules
This repo (**Perplexity-Tools**) is the **top-level orchestrator and instance manager**:
1. **Check before creating**: Consult `.state/agents.json` via `AgentTracker`.
2. **Reuse existing**: Return conflict if matching running agent exists (override with `force=true`).
3. **Conflict resolution**: Ask user before overriding idempotency.
4. **Destroy on completion**: Mark agents stopped when tasks complete.

---

## Changelog

### v0.9.6.0 (2026-03-27)
- **Orchestration**: Full hardware profile awareness implemented [web:40].
- **Strategies**: Adapted durable workflow and intelligent routing for multi-computer LAN.
- **Models**: Updated primaries to Qwen 3.5 series (9B MLX on Mac, 35B MoE on Dell).
- **Hardening**: Reinforced VRAM safety rules and hardware-bound routing.

### v0.9.1.0 (2026-03-22)
- Added SKILL.md with complete model selection logic
- Added Qwen3-30B-A3B as critic, refiner, and offline fallback
- Added Perplexity API integration (Claude Sonnet 4.5 + Grok 4.1)
- Added 4 runtime modes (Mac-only, Dell-only, LAN-full, LM-Studio-MLX)
- Integrated with ultrathink-system and ECC-tools
