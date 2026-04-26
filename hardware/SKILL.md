# Hardware Abstraction Layer — Perpetua-Tools
# hardware/SKILL.md
# Decoupled hardware profiles for role-based agent assignment.
# Synchronized across all repos. Governs VRAM/RAM limits for model routing.
# Last updated: 2026-04-08 | Version: 0.9.9.7

---

## Hardware Profiles

All hardware-specific configuration lives here. `ModelRegistry` reads this file
before selecting any model. Rules: never assign a model that exceeds the profile's
`max_model_vram_gb` or `max_model_ram_gb` limits.

> **Machine-enforced affinity policy:** See `config/model_hardware_policy.yml`.
> That YAML file is the authoritative runtime source for `NEVER_MAC` and
> `NEVER_WIN`. This markdown is the human-readable hardware guide.

---

### Profile: mac-studio

```yaml
profile_id: mac-studio
display_name: "Mac Mini / Mac Studio (Apple Silicon)"
architecture: apple-silicon
chip_family: [M2 Pro, M2 Max, M4 Pro, M4 Max]
unified_memory_gb: 16    # minimum tested; 24/32/64/96 also supported
vram_model: unified      # no discrete VRAM boundary — all unified
max_model_size_b: 30     # safe ceiling for 16GB; 70B+ needs 64GB+
max_model_vram_gb: null  # N/A — unified memory, no VRAM ceiling
max_context_tokens: 4096   # LM Studio conservative for M2; hardware cap is 32768
preferred_backend: lm-studio  # v0.9.9.1+: LM Studio primary (MLX weights loaded natively)
fallback_backend: ollama       # mlx-lm via CLI is also a valid alternative

# Geekbench 6 reference (M2 Pro 10-core)
# Single-core: 2686 | Multi-core: 12987 | Metal GPU: 74546
# M4 Pro 12-core: ~3900-4000 SC | ~20000 MC | ~90k-110k Metal (+45-55% over M2 Pro)

recommended_models:
  - id: glm-5.1:cloud
    ollama_tag: glm-5.1:cloud
    backend: ollama
    roles: [orchestrator, strategy, architecture, top-level]
    min_unified_memory_gb: 16
    tokens_per_second_est: provider-dependent
    notes: "Primary thin Mac orchestrator when the live probe succeeds; immediate fallback is Mac LM Studio."
  - id: Qwen3.5-9B-MLX-4bit
    hf_repo: mlx-community/Qwen3.5-9B-4bit
    backend: lm-studio
    lm_studio_context: 4096   # conservative — safe on M2 Pro 16GB
    gpu_offload: full          # Metal full offload
    roles: [orchestrator, final-validator, presenter, top-level]
    min_unified_memory_gb: 16
    tokens_per_second_est: 60-120
    notes: "Primary Mac orchestrator (v0.9.9.1+). Roles: orchestrate, validate, present."
  - id: qwen3.5-9b-mlx-4bit
    ollama_tag: mlx-community/Qwen3.5-9B-4bit
    backend: mlx
    roles: [top-level, general, orchestrator, manager]
    min_unified_memory_gb: 16
    tokens_per_second_est: 60-120
    notes: "Legacy MLX-LM path. Still valid; use LM Studio model above for v0.9.9.1+."
  - id: qwen3-30b-a3b-mlx
    ollama_tag: mlx-community/Qwen3-30B-A3B-4bit
    backend: mlx
    roles: [critic, refiner, strategy, fallback]
    min_unified_memory_gb: 24
    tokens_per_second_est: 20-40
    notes: "Needs 24GB+ unified memory. Use as critic/refiner."
  - id: qwen3.5:35b-a3b-q4_K_M
    ollama_tag: qwen3.5:35b-a3b-q4_K_M
    backend: ollama
    roles: [fallback, subagent, critic]
    min_unified_memory_gb: 16
    notes: "Known backup fallback model. Keep documented, but do not treat as the primary Mac orchestrator."

default_primary_model: glm-5.1:cloud
default_fallback_model: Qwen3.5-9B-MLX-4bit
```

---

### Profile: win-rtx3080

```yaml
profile_id: win-rtx3080
display_name: "Dell Precision 3660 (Intel i9-12900K, RTX 3080 10GB)"
architecture: x86-64
cpu: Intel Core i9-12900K
cpu_cores: 16 (8P + 8E)
ram_gb: 32
vram_gb: 10          # RTX 3080 10GB — hard ceiling for GPU layers
max_model_vram_gb: 10
max_model_size_b: 35  # 35B MoE models (A3B active params) fit with q4
max_context_tokens: 16384  # LM Studio with gpu_offload=40 layers frees RAM for longer context
preferred_backend: lm-studio  # v0.9.9.1+: LM Studio primary (GGUF weights, CUDA offload)
fallback_backend: ollama       # still valid for Ollama-compatible GGUF models
cuda_available: true

# LM STUDIO ENV — set in LM Studio UI or .env:
# LM_STUDIO_WIN_ENDPOINTS=http://192.168.254.100:1234
# LMS_WIN_MODEL=Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2
# LMS_WIN_GPU_OFFLOAD=40   # offload 40 layers to RTX 3080

# OLLAMA ENV (fallback) — bake into shell profile or Modelfile if using Ollama:
# OLLAMA_FLASH_ATTENTION=1       # crucial — speeds up RTX 3080 significantly
# OLLAMA_KV_CACHE_TYPE=q8_0      # compresses KV cache, saves ~2GB VRAM
# OLLAMA_NUM_PARALLEL=1          # prevent dual-task GPU contention

recommended_models:
  - id: Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2
    gguf_file: Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2-Q4_K_M.gguf
    hf_repo: bartowski/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2-GGUF
    backend: lm-studio
    gpu_offload: 40             # 40 layers to RTX 3080 10GB; remainder on CPU RAM
    lm_studio_context: 16384
    roles: [coder, checker, refiner, executor, verifier, subagent, fallback, autoresearch-coder]
    notes: "Primary Windows heavy coder and autoresearch executor (v0.9.9.7). Backend-agnostic GGUF."
  - id: gemma-4-26B-A4B-it-Q4_K_M
    gguf_file: gemma-4-26B-A4B-it-Q4_K_M.gguf
    hf_repo: lmstudio-community/gemma-4-26B-A4B-it-GGUF
    backend: lm-studio
    gpu_offload: 35
    lm_studio_context: 16384
    roles: [general, coding, executor, subagent, fallback]
    notes: "Gemma 4 26B MoE (4B active params). LM Studio community build — auto-detects. Secondary to Qwen 27B."
  - id: qwen3.5-35b-a3b-q4
    ollama_tag: frob/qwen3.5:35b-a3b-instruct-ud-q4_K_M
    backend: ollama
    roles: [coding, autoresearch-coder, top-level, heavy-reasoning]
    vram_usage_gb: 8.5   # q4_K_M leaves ~1.5GB for KV cache
    num_gpu_layers: 32
    num_ctx: 8192
    notes: "Legacy Ollama path. Still valid; use LM Studio model above for v0.9.9.1+."
  - id: qwen3-coder:14b
    ollama_tag: qwen3-coder:14b
    backend: ollama
    roles: [coding, autoresearch-coder, subagent]
    vram_usage_gb: 6.5
    num_gpu_layers: 35
    num_ctx: 32768
    notes: "Fallback coder for autoresearch and general coding when Windows LM Studio Qwen 27B is unavailable."
  - id: qwen3-30b-critic
    ollama_tag: qwen3:30b-a3b-instruct-q4_K_M
    backend: ollama
    roles: [critic, refiner, autoresearch-critic, strategy, fallback]
    vram_usage_gb: 9.0
    num_gpu_layers: 32
    num_ctx: 8192
    notes: "Critic/evaluator. High quality, fits 10GB with q4_K_M."

default_primary_model: Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2
default_fallback_model: qwen3.5-35b-a3b-q4
```

---

## Role → Hardware Assignment Matrix

The orchestrator MUST respect this table. Never assign a model
that exceeds the profile's VRAM/RAM ceiling.

| Role | Preferred Hardware | Model | Constraint |
|---|---|---|---|
| `orchestrator` / `strategy` / `architecture` | mac-studio | glm-5.1:cloud via local Ollama | live probe must pass |
| `final-validator` / `presenter` | mac-studio | Qwen3.5-9B-MLX-4bit (LM Studio) | NEVER_WIN; context≤4096 conservative |
| `coder` / `checker` / `executor` / `verifier` / `autoresearch-coder` | win-rtx3080 | Qwen3.5-27B (LM Studio) | NEVER_MAC; gpu_offload=40, context≤16384 |
| `refiner` / `subagent` | win-rtx3080 | Qwen3.5-27B (LM Studio) | NEVER_MAC; gpu_offload=40 |
| `general` / `coding` (secondary) | win-rtx3080 | gemma-4-26B-A4B-it-Q4_K_M (LM Studio) | NEVER_MAC; gpu_offload=35, context≤16384 |
| `coding` / `autoresearch-coder` | win-rtx3080 | qwen3.5-35b-a3b-q4 (Ollama fallback) | ≤10GB VRAM, num_ctx≤8192 |
| `critic` / `refiner` (Ollama path) | win-rtx3080 | qwen3-30b-critic | ≤10GB VRAM |
| `standard` / `subagent` | mac-studio | Qwen3.5-9B-MLX-4bit | NEVER_WIN; 16GB+ unified |
| `synthesis` | mac-studio | Qwen3.5-9B-MLX-4bit | NEVER_WIN; context≤4096 |
| `strategy` / `architecture` | cloud or win | claude-4-5 or qwen3-30b | online or local |
| `realtime` / `finance` | cloud | grok-4-1-thinking | online only |
| `autoresearch-critic` | win-rtx3080 | qwen3-30b-critic | ≤10GB VRAM |

---

## Fallback Degradation Chain

```
Ollama Mac (port 11434)    ← primary thin orchestrator: glm-5.1:cloud when probe passes
  ↓ GLM offline / rate-limited
LM Studio Win (port 1234)  ← primary heavy coder: Qwen3.5-27B, gpu_offload=40, context 16384
  ↓ Win offline / LM Studio not running
LM Studio Mac (port 1234)  ← orchestrator + validator fallback: Qwen3.5-9B-MLX-4bit, context 4096
  ↓ Mac LM Studio unreachable
Ollama Win (port 11434)    ← fallback: qwen3-coder:14b, qwen3-30b critic, qwen3.5:35b backup
  ↓ Ollama Win unreachable
Shared Ollama backup       ← qwen3.5:35b-a3b-q4_K_M
  ↓ All local backends down
Cloud fallback (Perplexity → cost_guard check first)
  ↓ Cost limit hit
DEGRADED: return cached result or queue task
```

---

## VRAM Safety Rules (win-rtx3080)

**LM Studio path (v0.9.9.1+ primary):**
- **GPU offload**: `gpu_offload: 40` layers → ~9GB VRAM for Qwen3.5-27B Q4_K_M
- **Context**: 16384 tokens safe with 40-layer offload (remaining layers on CPU/RAM)
- **VRAM ceiling**: Still hard-capped at 10GB — never offload more than 40 layers for 27B Q4
- **Parallelism**: LM Studio `concurrent_slots: 1` — single request at a time on RTX 3080

**Ollama path (fallback):**
- **Hard ceiling**: `max_model_vram_gb: 10` — never load models > 9.5GB weights
- **KV cache**: Use `OLLAMA_KV_CACHE_TYPE=q8_0` to compress (saves ~1.5-2GB)
- **Parallelism**: `OLLAMA_NUM_PARALLEL=1` — RTX 3080 cannot handle concurrent requests
- **Flash Attention**: `OLLAMA_FLASH_ATTENTION=1` — required for speed on Ampere arch
- **Context limit**: Keep `num_ctx ≤ 8192` for 35B MoE models on 10GB VRAM (Ollama only)

## MLX Tips (mac-studio)

- **Unified memory**: No discrete VRAM ceiling — model size limited by total RAM only
- **16GB RAM**: Stick to 7B–13B 4-bit models for comfortable inference
- **24–32GB RAM**: 30B models run comfortably
- **64GB+ RAM**: 70B+ models feasible
- **Speed**: 60–120+ tok/s on M2 Pro (7B-8B 4-bit); faster on M4 Pro
- **Installer**: `brew install uv && uv pip install mlx-lm` (preferred over pip)
- **Easiest path**: LM Studio — hands-down easiest for 95% of Mac users

---

## Synchronization Contract

This file is the **single source of truth** for hardware profiles.

`config/model_hardware_policy.yml` is the **single source of truth** for
machine-enforced model affinity. Do not duplicate the full policy in markdown;
cite the YAML and keep examples aligned with it.

- `config/models.yml` → references profile_ids from this file
- `config/routing.yml` → respects `max_model_vram_gb` constraints
- `orchestrator/model_registry.py` → loads this file at startup
- `agent_launcher.py` → reads profiles to build routing state
- `hardware/Modelfile.win-rtx3080` → bakes per-profile Ollama params
- `scripts/check_docs_sync.py` → auto-diff checker that validates this file against `config/models.yml`

**Never hardcode IPs or VRAM limits outside this file.**

---

## Changelog

### v0.9.9.2 (2026-04-06)
- **win-rtx3080**: Add `gemma-4-26B-A4B-it-Q4_K_M` (lmstudio-community) as secondary LM Studio model (priority 16, gpu_offload=35, roles: general/coding/executor/subagent/fallback)
- **agent_launcher**: Add `check_lmstudio_worker()` — now probes Windows LM Studio port 1234 alongside Ollama port 11434; routing state includes `lmstudio_endpoint`, `lmstudio_model`, `lmstudio_detected`
- **hardware**: Add `gemma-4-26b-setup.md` setup reference card for known-models folder

### v0.9.9.1 (2026-04-04)
- **win-rtx3080**: `preferred_backend` ollama → lm-studio; add canonical primary model `Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2` (gpu_offload=40, context 16384); legacy Ollama models preserved as fallback entries
- **mac-studio**: `preferred_backend` mlx → lm-studio; add canonical primary model `Qwen3.5-9B-MLX-4bit` (context 4096 conservative, Metal full offload); legacy MLX entries preserved
- **Fallback chain**: LM Studio Win → LM Studio Mac → Ollama Win → Ollama Mac → Cloud
- **Role matrix**: added orchestrator/final-validator/presenter roles for mac-studio; coder/checker/refiner/executor/verifier roles for win-rtx3080 via LM Studio
- **Sync**: `check_docs_sync.py` added as enforcement gate [SYNC]

### v0.9.9.0 (2026-03-30)
- Version freeze: all files synchronized to 0.9.9.0
