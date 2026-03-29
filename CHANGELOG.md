# Changelog — Perplexity-Tools

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Cross-repo changes affecting ultrathink-system are marked with `[SYNC]`.

---
## [0.9.8.0] - 2026-04-24

### Security

- **orchestrator.py**: Rate limiting added via `slowapi` (OWASP API4) [SYNC]
- **orchestrator.py**: Input validation — bounded `task_description` with `max_length=8000` (OWASP API3+API4) [SYNC]
- **orchestrator.py**: `ALLOWED_HOSTS` middleware support via env var [SYNC]
- **orchestrator.py**: API key startup validation with warning log [SYNC]

### Fixed

- **orchestrator.py**: Migrated `@validator` to Pydantic V2 `@field_validator` + `@classmethod` (deprecation fix) [SYNC]

### Synced with ultrathink-system

- Both repos synchronized to v0.9.8.0 [SYNC]
- `api_server.py` receives same Pydantic V2 migration [SYNC]

---


## [0.9.7.0] - 2026-03-28

### Added
- **AFRP cross-reference**: ultrathink-system layer now documents AFRP (pre-router gate) in 4-layer architecture table [SYNC]

### Fixed
- **orchestrator.py**: Removed git commit message fragment appended to REDIS_HOST line (syntax error)
- **orchestrator.py**: Replaced bare IP `192.168.1.100` with `OLLAMA_WINDOWS_ENDPOINT` env var
- **orchestrator/fastapi_app.py**: Updated stale version `0.9.0.0` → `0.9.7.0`
- **orchestrator/autoresearch_bridge.py**: Removed 3x confidential folder references
- **requirements.txt**: Updated header comment version

### Synced with ultrathink-system
- Both repos synchronized to v0.9.7.0 [SYNC]
- ultrathink-system introduces AFRP as mandatory pre-router gate [SYNC]

---

## [0.9.6.0] - 2026-03-27

### Added
- **LAN Continuity**: LAN Detect & Resume for seamless multi-computer operation [SYNC]
- **Spawn Reconciliation**: Pre-flight spawn detection and reconciliation before model spawning [SYNC]
- **Short Persistence Log**: `.state/session.log` for low-overhead session tracking
- `orchestrator/lan_discovery.py` — LAN-wide AI model discovery
- `orchestrator/spawn_reconciliation.py` — ECC and autoresearch spawn reconciliation registry
- `tests/test_lan_discovery.py` — LAN discovery test coverage

### Changed
- SKILL.md updated to v0.9.6.0 with hardware-aware multi-computer orchestration
- Models updated to Qwen 3.5 series (9B MLX on Mac, 35B MoE on Dell)
- `orchestrator.py` hardened with VRAM safety rules and hardware-bound routing
- Adapted durable workflow and intelligent routing for multi-computer LAN [SYNC]

### Synced with ultrathink-system
- Both repos synchronized to v0.9.6.0
- ultrathink `api_server.py` updated to v0.9.6.0 with GPU reconciliation
- Cross-repo SKILL.md references established for recursive sub-skill loading

## [0.9.5.0] - 2026-03-27

### Added

- `hardware/SKILL.md` – Hardware abstraction layer defining `mac-studio` and `win-rtx3080` profiles with role-based model assignment matrix, VRAM/RAM safety rules, and MLX/LM Studio guidance
- `hardware/Modelfile.win-rtx3080` – Ollama Modelfile for Qwen3.5-35B-A3B on Dell RTX 3080 with Flash Attention and KV cache compression
- `hardware/Modelfile.mac-studio` – Ollama Modelfile for Qwen3.5-9B manager agent on Apple Silicon with unified memory tuning
- `agent_launcher.py` – Hardware detection script with graceful degradation (Mac+Windows → Mac-only → LM Studio → Cloud), outputs routing state to `.state/agents.json`
- `setup_wizard.py` – Idempotent installation wizard that scans for existing AI software (Ollama, LM Studio, MLX) and guides tiered setup (Priority 1: easiest, Priority 2: advanced distributed)

### Changed

- Architecture: Formalized hardware-aware orchestration with modular hardware profiles as single source of truth
- Workflow: Launcher script now auto-detects available hardware and routes coder/heavy-reasoning tasks to RTX 3080 when online, falls back to Mac for synthesis/management
- Installation: Priority 1 path recommends LM Studio for 95% of Mac users; Priority 2 advanced path for distributed Mac+Windows setup with explicit caveats

### Technical Notes

- Qwen3.5 model updates: `frob/qwen3.5:35b-a3b-instruct-ud-q4_K_M` (35B MoE) on Windows, `qwen3.5:9b-instruct` on Mac
- RTX 3080 tuning: `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_NUM_PARALLEL=1` required for optimal performance
- MLX path preferred on Apple Silicon (60-120+ tok/s on M2/M4 Mac Mini for 7B-8B 4-bit models)
- Hardware detection timeout: 3 seconds to avoid blocking when remote worker offline
- Future: `config/models.yml` and `config/routing.yml` updates to reference `profile_id` from hardware/SKILL.md (deferred to next commit)

---


## [0.9.4.3] - 2026-03-26

### Added
- `tests/test_routing.py` — routing.yml + ultrathink route unit tests [SYNC]
- `.github/workflows/ci.yml` — CI pipeline with pytest + routing.yml validation
- `config/routing.yml` — `deep_reasoning` and `code_analysis` ultrathink routes [SYNC]
- `.env.example` — full `ULTRATHINK_ENDPOINT`, `ULTRATHINK_TIMEOUT`, `ULTRATHINK_ENABLED` vars [SYNC]

### Changed
- `.env.example` — updated version header to v0.9.4.3, expanded ultrathink section
- `config/routing.yml` — added ultrathink endpoint/fallback/timeout metadata to deep reasoning routes

### Synced with ultrathink-system
- Both repos now at v0.9.4.3
- `api_server.py` added to ultrathink-system (POST /ultrathink + GET /health)
- Shared `.env` contract documented in both repos
- PERPLEXITY_BRIDGE.md + SYNC_ANALYSIS.md in ultrathink-system docs

---

## [0.9.0.0] - 2026-03-22

### Added
- Initial Perplexity-Tools release
- Multi-model orchestrator with local Ollama + Perplexity cloud fallback
- `.agents/skills/Perplexity-Tools/` skill bundle for Claude/Codex/Cowork
- `config/routing.yml` — task-type to model-role routing
- `config/models.yml` — model registry with device affinity
- `config/devices.yml` — LAN device configuration (Mac + Windows)
- `orchestrator/autoresearch_bridge.py` — idempotent karpathy/autoresearch sync
- Budget controls: `MAX_DAILY_SPEND`, `MAX_PERPLEXITY_CALLS_DAY`
- Redis state persistence for agent deduplication

---

## Notes

- ultrathink-system CHANGELOG: https://github.com/diazMelgarejo/ultrathink-system/blob/main/CHANGELOG.md
- 4-layer architecture: Perplexity-Tools → ultrathink-system → ECC Tools → autoresearch
- Priority rule: PT SKILL.md runs first; ultrathink called for `reasoning_depth=ultra` only
