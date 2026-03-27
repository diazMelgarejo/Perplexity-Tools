# Changelog — Perplexity-Tools

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Cross-repo changes affecting ultrathink-system are marked with `[SYNC]`.

---

## [0.9.5.0] - 2025-03-26

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
