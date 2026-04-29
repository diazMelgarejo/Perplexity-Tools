# This is the Legacy Perpetua-Tools v0.9.9.8

> **Top-level idempotent multi-agent orchestrator for Mac + Windows**
> * we are moving to a new 2.0 repo soon!

---

## Architecture Overview

Four interoperable, independently configurable layers:

| Repo | Role | Config |
|------|------|--------|
| **Perpetua-Tools** (this repo) | Top-level orchestrator, agent lifecycle, fallback routing, idempotency | `config/devices.yml`, `config/models.yml`, `config/routing.yml` |
| **[orama-system](https://github.com/diazMelgarejo/orama-system)** | Reasoning methodology, 5-stage process, CIDF; routing methodology via `bin/skills/SKILL.md`; multi-agent registry is separately installable | `bin/skills/SKILL.md`, `bin/config/` |
| **[ECC Tools](https://github.com/affaan-m/everything-claude-code)** | Subagent auto-selection default logic for up to 5 Stage4 parallel Masterful Executor Agents (especially coders) | `.claude/ecc-tools.json` |
| **[uditgoenka/autoresearch](https://github.com/uditgoenka/autoresearch)** | Latest idempotent sync; research automation workflows and AI-driven research tools | Per autoresearch standard |

**Priority rule:**

- Top-level agents on Mac + Windows: **this repo's `SKILL.md` → `ModelRegistry` → fallback chain** (top-level model selection runs first).
- Subagents: **ECC-tools default logic** for ECC-style auto-selection (unless the top-level orchestrator overrides role assignment); supports up to 5 Stage4 parallel Masterful Executor Agents, especially coders.
- **orama-system** supplies reasoning and routing methodology; keep it **independently configurable** from this orchestrator's device/model YAML.
- **autoresearch** provides latest research automation workflows with idempotent sync.

---

## Key Properties

- **Idempotent**: checks `.state/agents.json` before spawning; if a matching running top-level agent already exists for the same role and task, **ask the user** before creating another (or pass `force=true` on `POST /orchestrate` after explicit confirmation).
- **Fallback logic**: local → online, device-preferred → shared → cloud.
- **Per-device**: Mac (`glm-5.1:cloud` via local Ollama, with LM Studio verifier/orchestrator fallback), Windows (LM Studio primary, Ollama fallback), or both on one shared Ollama.
- **Cost-guarded**: daily budget cap + 80% alert threshold.
- **Interoperable**: all four layers compatible via shared config contracts; **Perpetua-Tools** remains the top-level orchestrator and instance manager.

---

## Repository Structure

```
Perpetua-Tools/
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
└── implementation_templates.json     ← v1.0.0 templates (inherited from main)
```

---

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/diazMelgarejo/Perpetua-Tools
cd Perpetua-Tools
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

# 5. Smoke-test the Perplexity client
python scripts/test_perplexity.py --validate --base-url https://api.perplexity.ai --timeout 30

# 6. Orchestrate a task (idempotent — safe to call twice)
curl -X POST http://localhost:8000/orchestrate \\
  -H "Content-Type: application/json" \\
  -d '{"task": "Refactor auth module", "task_type": "coding", "preferred_device": "mac-studio"}'
```

---

## Perplexity Client

The Perplexity singleton supports a small set of ergonomic constructor options:

```python
from orchestrator.perplexity_client import PerplexityClient

client = PerplexityClient.get(
    validate=True,
    interactive=False,
    base_url="https://api.perplexity.ai",
    timeout=30.0,
)
```

- `validate=True` re-checks a stored key before reuse.
- `interactive=False` keeps the client quiet in non-TTY automation.
- `base_url` and `timeout` can be changed per environment or test harness.
- Use `client.stream(...)` for streaming responses; `chat(..., stream=True)` remains a compatibility path.

---

## Backend Modes

| Mode | Mac | Windows | Config |
|------|-----|---------|--------|
| **Shared Ollama** | client | server (or vice versa) | `OLLAMA_HOST=http://<ip>:11434` |
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
      │                        │
      │                   force=true?
      │                        │
     no                       yes
      │                        │
      └──────────┬─────────────┘
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

- **orama-system**: install per that repo; provides reasoning layer (`bin/skills/SKILL.md`) and optional multi-agent registry — **separately configurable** from this repo.
- **ECC Tools** ([affaan-m/everything-claude-code](https://github.com/affaan-m/everything-claude-code)): subagents use ECC auto-selection by default for up to 5x Stage-4 parallel Masterful Executor Agents (especially coders); configured via `.claude/ecc-tools.json`.
- **autoresearch** ([uditgoenka/autoresearch](https://github.com/uditgoenka/autoresearch)): latest idempotent sync for research automation workflows.
- All configs live in `config/` — prefer YAML + env (e.g. `OLLAMA_HOST`) over hardcoded hosts.

---

## Version

| Field | Value |
|-------|-------|
| Version | `0.9.9.8` |
| Branch | `main` |
| Compatible with | orama-system (reasoning layer; version per that repo), ECC Tools standard, uditgoenka/autoresearch (research automation) |
| Python | `3.11+` |
| Framework | FastAPI + httpx + PyYAML |
