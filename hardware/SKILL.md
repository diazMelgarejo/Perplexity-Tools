# Hardware Abstraction Layer — Perplexity-Tools
# hardware/SKILL.md
# Decoupled hardware profiles for role-based agent assignment.
# Synchronized across all repos. Governs VRAM/RAM limits for model routing.
# Last updated: 2026-03-28 | Version: 0.9.6.0

---

## Hardware Profiles

All hardware-specific configuration lives here. `ModelRegistry` reads this file
before selecting any model. Rules: never assign a model that exceeds the profile's
`max_model_vram_gb` or `max_model_ram_gb` limits.

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
max_context_tokens: 32768
preferred_backend: mlx   # MLX-LM: fastest on Apple Silicon, no VRAM ceiling
fallback_backend: ollama

# Geekbench 6 reference (M2 Pro 10-core)
# Single-core: 2686 | Multi-core: 12987 | Metal GPU: 74546
# M4 Pro 12-core: ~3900-4000 SC | ~20000 MC | ~90k-110k Metal (+45-55% over M2 Pro)

recommended_models:
  - id: qwen3.5-9b-mlx-4bit
    ollama_tag: mlx-community/Qwen3.5-9B-4bit
    backend: mlx
    roles: [top-level, general, orchestrator, manager]
    min_unified_memory_gb: 16
    tokens_per_second_est: 60-120
    notes: "Primary Mac orchestrator. ~60-120 tok/s on M2 Pro, faster on M4."
  - id: qwen3-30b-a3b-mlx
    ollama_tag: mlx-community/Qwen3-30B-A3B-4bit
    backend: mlx
    roles: [critic, refiner, strategy, fallback]
    min_unified_memory_gb: 24
    tokens_per_second_est: 20-40
    notes: "Needs 24GB+ unified memory. Use as critic/refiner."
  - id: qwen3-8b-instruct
    ollama_tag: qwen3:8b-instruct
    backend: ollama
    roles: [standard, subagent, synthesis]
    min_unified_memory_gb: 16
    notes: "Ollama fallback for standard tasks on Mac."

default_primary_model: qwen3.5-9b-mlx-4bit
default_fallback_model: qwen3:8b-instruct
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
max_context_tokens: 8192  # limit to save VRAM
preferred_backend: ollama
fallback_backend: lm-studio
cuda_available: true

# OLLAMA ENV — bake these into shell profile or Modelfile:
# OLLAMA_FLASH_ATTENTION=1       # crucial — speeds up RTX 3080 significantly
# OLLAMA_KV_CACHE_TYPE=q8_0      # compresses KV cache, saves ~2GB VRAM
# OLLAMA_NUM_PARALLEL=1          # prevent dual-task GPU contention

recommended_models:
  - id: qwen3.5-35b-a3b-q4
    ollama_tag: frob/qwen3.5:35b-a3b-instruct-ud-q4_K_M
    backend: ollama
    roles: [coding, autoresearch-coder, top-level, heavy-reasoning]
    vram_usage_gb: 8.5   # q4_K_M leaves ~1.5GB for KV cache
    num_gpu_layers: 32
    num_ctx: 8192
    notes: "MoE-optimized. 35B params, ~3.5B active. Fits RTX 3080 10GB with q4."
  - id: qwen3-coder-14b
    ollama_tag: qwen3-coder:14b
    backend: ollama
    roles: [coding, autoresearch-coder, subagent]
    vram_usage_gb: 6.5
    num_gpu_layers: 35
    num_ctx: 32768
    notes: "Preferred coder for autoresearch swarm. Lower VRAM than 35B."
  - id: qwen3-30b-critic
    ollama_tag: qwen3:30b-a3b-instruct-q4_K_M
    backend: ollama
    roles: [critic, refiner, autoresearch-critic, strategy, fallback]
    vram_usage_gb: 9.0
    num_gpu_layers: 32
    num_ctx: 8192
    notes: "Critic/evaluator. High quality, fits 10GB with q4_K_M."

default_primary_model: qwen3.5-35b-a3b-q4
default_fallback_model: qwen3-coder:14b
```

---

## Role → Hardware Assignment Matrix

The orchestrator MUST respect this table. Never assign a model
that exceeds the profile's VRAM/RAM ceiling.

| Role | Preferred Hardware | Model | Constraint |
|---|---|---|---|
| `orchestrator` / `manager` | mac-studio | qwen3.5-9b-mlx-4bit | 16GB+ unified memory |
| `coding` / `autoresearch-coder` | win-rtx3080 | qwen3.5-35b-a3b-q4 | ≤10GB VRAM, num_ctx≤8192 |
| `critic` / `refiner` | win-rtx3080 | qwen3-30b-critic | ≤10GB VRAM |
| `standard` / `subagent` | mac-studio | qwen3-8b-instruct | 16GB+ unified |
| `synthesis` | mac-studio | qwen3.5-9b-mlx-4bit | 16GB+ unified |
| `strategy` / `architecture` | cloud or win | claude-4-5 or qwen3-30b | online or local |
| `realtime` / `finance` | cloud | grok-4-1-thinking | online only |
| `autoresearch-critic` | win-rtx3080 | qwen3-30b-critic | ≤10GB VRAM |

---

## Fallback Degradation Chain

```
Distributed (Mac + Dell)  ← preferred when both online
  ↓ Dell offline / unreachable
Mac-Only Fallback         ← all roles reassigned to Mac models
  ↓ Ollama unreachable on Mac
Local LM Studio (if running)
  ↓ All local backends down
Cloud fallback (Perplexity → cost_guard check first)
  ↓ Cost limit hit
DEGRADED: return cached result or queue task
```

---

## VRAM Safety Rules (win-rtx3080)

- **Hard ceiling**: `max_model_vram_gb: 10` — never load models > 9.5GB weights
- **KV cache**: Use `OLLAMA_KV_CACHE_TYPE=q8_0` to compress (saves ~1.5-2GB)
- **Parallelism**: `OLLAMA_NUM_PARALLEL=1` — RTX 3080 cannot handle concurrent requests
- **Flash Attention**: `OLLAMA_FLASH_ATTENTION=1` — required for speed on Ampere arch
- **Context limit**: Keep `num_ctx ≤ 8192` for 35B MoE models on 10GB VRAM

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

- `config/models.yml` → references profile_ids from this file
- `config/routing.yml` → respects `max_model_vram_gb` constraints
- `orchestrator/model_registry.py` → loads this file at startup
- `agent_launcher.py` → reads profiles to build routing state
- `hardware/Modelfile.win-rtx3080` → bakes per-profile Ollama params

**Never hardcode IPs or VRAM limits outside this file.**
