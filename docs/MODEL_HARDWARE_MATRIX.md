# AI Agent Model × Hardware Profile Matrix

Canonical enumeration of all AI agent models and hardware device assignments across **Perplexity-Tools** (PT, repo #1, port 8000) and **ultrathink-system** (US, repo #2, port 8001).

---

## Perplexity-Tools — Model Registry

Local models, cloud APIs, and autoresearch swarm agents registered in `config/models.yml`.

### Local Models (Device-Bound)

| Model Name | Backend | Device | Host | Port | Priority | Roles | Reasoning Tag | Online |
|---|---|---|---|---|---|---|---|---|
| `qwen3-coder-14b` | ollama | **win-rtx3080** | `$DELL_ENDPOINT` (192.168.1.100) | 11434 | 5 | autoresearch-coder, coding, subagent, fallback | windows-local-coder | No |
| `qwen3-30b-autoresearch-critic` | ollama | **win-rtx3080** | `$DELL_ENDPOINT` (192.168.1.100) | 11434 | 6 | autoresearch-critic, critic, refiner, strategy, fallback | windows-local-critic | No |
| `qwen3.5:35b-a3b-q4_K_M` | ollama | **shared-ollama-host** | `$OLLAMA_HOST` (127.0.0.1) | 11434 | 10 | general, critic, refiner, fallback, subagent | local-default | No |
| `qwen3.5-9b-mlx` | mlx | **mac-studio** | 127.0.0.1 | 8081 | 20 | general, top-level, coding, subagent | mac-local | No |
| `qwen3.5-35b-a3b-lmstudio` | lm-studio | **win-rtx3080** | 127.0.0.1 | 1234 | 30 | general, coding, subagent, fallback | windows-local | No |

### Cloud / Online Models

| Model Name | Backend | Device | Host | Port | Priority | Roles | Reasoning Tag | Online |
|---|---|---|---|---|---|---|---|---|
| `sonar-reasoning-pro` | perplexity | **cloud** | api.perplexity.ai | 443 | 40 | research, top-level, realtime | online-research | Yes |
| `claude-4-5-thinking` | anthropic | **cloud** | api.anthropic.com | 443 | 50 | strategy, architecture, top-level | high-depth | Yes |
| `grok-4-1-thinking` | xai | **cloud** | api.x.ai | 443 | 60 | finance, realtime, market, top-level | realtime-specialist | Yes |

---

## Hardware Device Profiles

Defined in `config/devices.yml`. Each device supports one or more local runtimes.

| Device ID | OS | GPU/Chip | Default Backend | Alternative Runtimes | LAN IP | Port(s) |
|---|---|---|---|---|---|---|
| **mac-studio** | macOS | Apple Silicon (M-series) | MLX | Ollama, LM Studio | 192.168.1.101 | 8081 (MLX), 11434 (Ollama) |
| **win-rtx3080** | Windows | NVIDIA RTX 3080 | Ollama (CUDA) | LM Studio | 192.168.1.100 | 11434 (Ollama), 1234 (LM Studio) |
| **shared-ollama-host** | mixed | — | Ollama only | — | `$OLLAMA_HOST` (configurable) | 11434 |
| **cloud** | — | — | HTTPS API | — | internet | 443 |

---

## Task Type → Model Route Mapping

Defined in `config/routing.yml`. Maps task types to role chains and device affinity.

### Standard Tasks (Default Routes)

| Task Type | Primary Roles | Device Preference | Model Selection | Notes |
|---|---|---|---|---|
| `default` | top-level → general → fallback | any | priority-ordered | General-purpose tasks |
| `coding` | coding → top-level → fallback | mac (MLX) or win (Ollama) | qwen3.5-9b-mlx or qwen3-coder-14b | Code generation, review, debugging |
| `strategy` | strategy → architecture → top-level → fallback | cloud preferred | claude-4-5-thinking | Architecture, planning, system design |
| `finance` | finance → realtime → market → fallback | cloud required | grok-4-1-thinking | Financial analysis, market data, real-time queries |
| `research` | research → top-level → fallback | cloud preferred | sonar-reasoning-pro | Web research, synthesis, long-context analysis |
| `critic` | critic → refiner → fallback | win-rtx3080 or shared | qwen3.5:35b-a3b-q4_K_M | Refinement, quality review, elegance scoring |
| `subagent` | subagent → general → fallback | any | priority-ordered | Subagent tasks delegated by top-level |
| `realtime` | realtime → market → research → fallback | cloud required | grok-4-1-thinking, sonar-reasoning-pro | Live data, current events, monitoring |

### Ultrathink Routes (Special)

Routed to **ultrathink-system (port 8001)** via HTTP bridge. Require `ULTRATHINK_ENDPOINT` env var.

| Task Type | Primary Roles | Device Affinity | Endpoint | Timeout | Fallback Model |
|---|---|---|---|---|---|
| **`deep_reasoning`** | ultrathink → strategy → top-level → fallback | ultrathink bridge | `$ULTRATHINK_ENDPOINT`:8001 | `$ULTRATHINK_TIMEOUT` | local_qwen30b |
| **`code_analysis`** | ultrathink → coding → top-level → fallback | ultrathink bridge | `$ULTRATHINK_ENDPOINT`:8001 | `$ULTRATHINK_TIMEOUT` | local_qwen30b (primary: qwen3-coder-14b) |

#### Ultrathink Bridge — Model Selection (via `api_server.py`)

The ultrathink HTTP bridge (`/ultrathink` endpoint, port 8001) selects its own model at call time:

| Model | Role | Device | Selection Rule |
|---|---|---|---|
| `qwen3.5:35b-a3b-q4_K_M` | PRIMARY | **win-rtx3080** (192.168.1.100) | Default for all tasks |
| `qwen3-coder:14b` | CODE-SPECIFIC | **win-rtx3080** | Used when task_type=code_analysis |
| `qwen3:8b-instruct` | FALLBACK | **mac-studio** (localhost) | When Windows unreachable |

### Autoresearch Routes (Special)

GPU-intensive ML experiment swarms. Require preflight sync and GPU lock coordination.

| Task Type | Agent(s) | Device Affinity | Model | Responsibility |
|---|---|---|---|---|
| `autoresearch` | coder + critic + orchestrator | win (coder), mac (critic + orchestrator) | see below | Full ML experiment loop via karpathy/autoresearch |
| `autoresearch-coder` | autoresearch-coder | **win-rtx3080** | qwen3-coder-14b | Edit train.py, scp deploy, ssh dispatch, flip GPU lock |
| `autoresearch-evaluator` | autoresearch-evaluator | **mac-studio** | qwen3-30b-autoresearch-critic | Parse val_bpb from log.txt, write swarm_state.md |
| `autoresearch-orchestrator` | autoresearch-orchestrator | **mac-studio** | qwen3.5-9b-mlx or claude-4-5-thinking | Propose hypothesis, coordinate lifecycle |
| `ml-experiment` | — | — | — | Alias for `autoresearch`; routes identically |

---

## Ultrathink-System — 7-Agent Pipeline

These agents execute **inside** ultrathink-system (port 8001) as part of the reasoning pipeline. They share whatever model `api_server.py` selected — they are **role-typed**, not model-bound.

| Agent ID | Type | Stage | Max Instances | Device | Key Tools |
|---|---|---|---|---|---|
| `orchestrator` | coordinator | — | 1 | mac-studio (US server) | state_manager, message_bus, all_agent_delegators |
| `context-agent` | specialist | 1 | 3 | mac-studio | git_history, code_analyzer, lessons_db |
| `architect-agent` | specialist | 2 | 2 | mac-studio | module_decomposer, interface_designer, diagram_generator |
| `refiner-agent` | specialist | 3 | 2 | mac-studio | complexity_analyzer, redundancy_detector, rubric_evaluator |
| `executor-agent` | worker | 4 | 5 | mac-studio | code_generator, test_generator, linter, performance_profiler |
| `verifier-agent` | validator | 4.5 | 2 | mac-studio | test_runner, diff_analyzer, scenario_generator |
| `crystallizer-agent` | documenter | 5 | 1 | mac-studio | diagram_generator, lessons_db, documentation_writer |

**Model used by ultrathink pipeline** (selected by `api_server.py`, not individual agents):

| Context | Model | Device | Port |
|---|---|---|---|
| Primary (most tasks) | `qwen3.5:35b-a3b-q4_K_M` | win-rtx3080 | 192.168.1.100:11434 |
| Code-specific | `qwen3-coder:14b` | win-rtx3080 | 192.168.1.100:11434 |
| Fallback (Windows unreachable) | `qwen3:8b-instruct` | mac-studio | 127.0.0.1:11434 |

---

## Summary: Model Assignments by Device

### Windows Device (win-rtx3080, 192.168.1.100)

**Primary Ollama models:**
- `qwen3.5:35b-a3b-q4_K_M` — general, critic, fallback, ultrathink primary
- `qwen3-coder:14b` — autoresearch-coder, code_analysis, code_analysis ultrathink
- `qwen3-30b-autoresearch-critic` — autoresearch-critic, evaluator, strategy
- `qwen3.5-35b-a3b-lmstudio` — general (LM Studio alt), coding, subagent

**Use cases:**
- All ultrathink deep_reasoning and code_analysis tasks (via HTTP bridge)
- Autoresearch coder and critic agents
- Fallback for Mac when needed

### Mac Device (mac-studio, 192.168.1.101)

**Primary MLX model:**
- `qwen3.5-9b-mlx` — top-level, general, coding, subagent, autoresearch-orchestrator

**Fallback Ollama:**
- `qwen3:8b-instruct` — when ultrathink Windows unreachable

**Use cases:**
- Local development and testing
- Autoresearch orchestrator agent
- Fallback for ultrathink bridge

### Shared Ollama Host

- `qwen3.5:35b-a3b-q4_K_M` — configurable via `$OLLAMA_HOST` env var
- Allows both Mac and Windows to share a single Ollama endpoint
- Optional; not required if devices run local Ollama

### Cloud Services

- **Perplexity sonar-reasoning-pro** — research, realtime
- **Anthropic claude-4-5-thinking** — strategy, architecture, autoresearch-orchestrator (alt)
- **xAI grok-4-1-thinking** — finance, realtime, market

---

## Model Priority Order

Lower priority number = preferred. Orchestrator tries models in this order for any given role.

1. **Priority 5–6** — Autoresearch specialists (local Windows only)
2. **Priority 10** — Shared Ollama default (qwen3.5:35b)
3. **Priority 20** — Mac MLX (qwen3.5-9b)
4. **Priority 30** — Windows LM Studio (qwen3.5-35b alt)
5. **Priority 40–60** — Cloud models (online, require API keys)

---

## Key Invariants

- **Autoresearch is Windows-primary:** Coder agent **must** run on win-rtx3080 (CUDA for training)
- **Ultrathink is Windows-primary:** Default model on 192.168.1.100; Mac is fallback only
- **All 7 ultrathink agents run on one model:** No per-agent model assignment; pipeline coordinator selects once
- **Cloud models are never the first choice for local/private tasks:** deep_reasoning and code_analysis avoid cloud unless ultrathink bridge explicitly unreachable
- **Context window sizes:** Ultrathink primary (32k) < cloud thinking models (128k–200k+), allowing for extended reasoning with cloud fallback

---

*Last updated: 2026-03-30*
*Version: v0.9.9.0 (pre-v1.0 RC)*
