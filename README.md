# Perplexity-Tools v0.9.4.1

> **Top-level idempotent multi-agent orchestrator for Mac + Windows**  
> Standardized first on `v0.9.0.0` — branch `v0.9.0.0` of [`diazMelgarejo/Perplexity-Tools`](https://github.com/diazMelgarejo/Perplexity-Tools); *`main` branch is ahead now ahead at v0.9.4.1*

---

## Architecture Overview

Three interoperable, independently configurable layers:

| Repo | Role | Config |
|------|------|--------|
| **Perplexity-Tools** (this repo) | Top-level orchestrator, agent lifecycle, fallback routing, idempotency | `config/devices.yml`, `config/models.yml`, `config/routing.yml` |
| **[ultrathink-system](https://github.com/diazMelgarejo/ultrathink-system)** | Reasoning methodology, 5-stage process, CIDF; routing methodology via `single-agent/SKILL.md`; multi-agent registry is separately installable | `single-agent/SKILL.md`, `multi-agent/config/` |
| **ECC Tools** | Subagent auto-selection default logic | Per ECC Tools standard |

**Priority rule:**

- Top-level agents on Mac + Windows: **this repo’s `SKILL.md` → `ModelRegistry` → fallback chain** (top-level model selection runs first).
- Subagents: **ECC-tools default logic** for ECC-style auto-selection (unless the top-level orchestrator overrides role assignment).
- **ultrathink-system** supplies reasoning and routing methodology; keep it **independently configurable** from this orchestrator’s device/model YAML.

---

## Key Properties

- **Idempotent**: checks `.state/agents.json` before spawning; if a matching running top-level agent already exists for the same role and task, **ask the user** before creating another (or pass `force=true` on `POST /orchestrate` after explicit confirmation).
- **Fallback logic**: local → online, device-preferred → shared → cloud.
- **Per-device**: Mac (MLX / shared Ollama), Windows (Ollama / LM Studio), or both on one shared Ollama.
- **Cost-guarded**: daily budget cap + 80% alert threshold.
- **Interoperable**: all three layers compatible via shared config contracts; **Perplexity-Tools** remains the top-level orchestrator and instance manager.

---

## Repository Structure

```
Perplexity-Tools/
├── SKILL.md                          ← Top-level model-selection skill
├── orchestrator/
│   ├── __init__.py
│   ├── agent_tracker.py              ← Idempotent agent lifecycle (file-persisted)
│   ├── model_registry.py             ← Per-device model selection + fallback chain
│   ├── connectivity.py               ← Ollama / MLX / LM Studio / online health checks
│   ├── cost_guard.py                 ← Daily budget cap + 80%-alert
│   ├── perplexity_client.py          ← Perplexity API (sonar-reasoning-pro)
│   └── fastapi_app.py                ← REST API: /health /orchestrate /agents /models
├── config/
│   ├── devices.yml                   ← Mac, Windows, shared-Ollama profiles
│   ├── models.yml                    ← All models: local + online, per device + backend
│   └── routing.yml                   ← task_type → role → model fallback chain
├── .state/                           ← Runtime: agents.json, budget.json (gitignored)
├── .env.example
├── requirements.txt
├── multi_agent_labs_strategy.json    ← v1.0.0 strategy (inherited from main)
└── implementation_templates.json    ← v1.0.0 templates (inherited from main)
```

---

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/diazMelgarejo/Perplexity-Tools
cd Perplexity-Tools
git checkout
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env: set PERPLEXITY_API_KEY, OLLAMA_HOST, daily budget, etc.

# 3. Run orchestrator API
python -m orchestrator.fastapi_app
# → http://localhost:8000/docs

# 4. Check health (detects all backends)
curl "http://localhost:8000/health"

# 5. Orchestrate a task (idempotent — safe to call twice)
curl -X POST http://localhost:8000/orchestrate \
  -H "Content-Type: application/json" \
  -d '{"task": "Refactor auth module", "task_type": "coding", "preferred_device": "mac-studio"}'
```

---

## Backend Modes

| Mode | Mac | Windows | Config |
|------|-----|---------|--------|
| **Shared Ollama** | client | server (or vice versa) | `OLLAMA_HOST=http://<win-ip>:11434` |
| **MLX on Mac only** | MLX server on :8081 | LM Studio on :1234 | default |
| **Independent** | MLX or Ollama | Ollama or LM Studio | no shared host needed |

---

## Idempotency Flow

```
POST /orchestrate
       │
       ▼
  compute task_hash
       │
       ▼
  find_existing(role, task_hash)
       │
  found? ──yes──► return conflict prompt → ask user
       │                                      │
       │                              force=true?
       │                                │
       no                              yes
       │                                │
       └──────────┬─────────────────────┘
                  ▼
          check budget
                  │
                  ▼
          route_task() → fallback chain
                  │
                  ▼
          register agent → return agent + chain
```

---

## Compatible Repos

- **ultrathink-system**: install per that repo; provides reasoning layer (`single-agent/SKILL.md`) and optional multi-agent registry — **separately configurable** from this repo.
- **ECC Tools**: subagents use ECC auto-selection by default.
- All configs live in `config/` — prefer YAML + env (e.g. `OLLAMA_HOST`) over hardcoded hosts.

---

## Version

| Field | Value |
|-------|-------|
| Version | `0.9.4.1` |
| Branch | `main` |
| Compatible with | ultrathink-system (reasoning layer; version per that repo), ECC Tools standard |
| Python | `3.11+` |
| Framework | FastAPI + httpx + PyYAML |
