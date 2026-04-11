# Gemma 4 26B A4B — Windows Setup Reference
# hardware/gemma-4-26b-setup.md
# Known hardware model card for win-rtx3080 (XPS 8950, RTX 3080 10GB)
# Last updated: 2026-04-06 | hardware/SKILL.md v0.9.9.2

---

## Model

| Field | Value |
|---|---|
| HF repo | `lmstudio-community/gemma-4-26B-A4B-it-GGUF` |
| File | `gemma-4-26B-A4B-it-Q4_K_M.gguf` |
| Size | ~16.8 GB |
| Architecture | Mixture of Experts (MoE): 26B total params, **4B active** |
| Quantization | Q4_K_M (LM Studio community — optimized, auto-detects) |

**Why lmstudio-community over bartowski?**

| Aspect | bartowski | lmstudio-community |
|---|---|---|
| Quant selection | Very large (IQ2_XXS → BF16, _L / _XL variants) | Focused (Q4_K_M, Q6_K, Q8_0) |
| Q4_K_M size | ~17 GB | ~16.8 GB |
| LM Studio auto-detect | Works fine | Best — built by LM Studio team |
| Speed on RTX 3080 | Very good | Slightly faster/more stable in LM Studio |
| Recommendation | Use if you want more quant options | **Use this for XPS 8950 + RTX 3080 "just works"** |

---

## LM Studio Load Settings (setup.sh defaults)

```
GPU Offload Layers : 35          # ~9.5 GB VRAM — safe ceiling for RTX 3080 10 GB
Context Length     : 16384       # tokens; safe with 35-layer offload + 32 GB RAM
Concurrent Slots   : 1           # RTX 3080 cannot handle concurrent requests
Flash Attention    : ON          # required for Ampere arch speed
```

**VRAM breakdown:**
- 35 layers × ~270 MB/layer ≈ 9.45 GB VRAM (GPU)
- Remaining ~18 layers → CPU RAM (32 GB available — no issue)
- KV cache for 16384 context ≈ 0.4 GB extra VRAM
- Total GPU: ~9.85 GB (within 10 GB ceiling)

---

## Environment Variables

Add to `.env` (or `.env.local` for overrides):

```bash
# Windows LM Studio — Gemma 4 26B
WINDOWS_LMS_PORT=1234
WINDOWS_LMS_MODEL=gemma-4-26B-A4B-it-Q4_K_M
LM_STUDIO_WIN_ENDPOINTS=http://192.168.254.100:1234   # adjust to your Windows IP
```

Override `WINDOWS_IP` if your Windows node has a different address:
```bash
WINDOWS_IP=192.168.254.100   # example; see network_autoconfig.py preferred_ips
```

---

## Autodetect Behavior

`agent_launcher.py` probes **both** endpoints on Windows startup:

```
WINDOWS_IP:11434/api/tags    → Ollama (existing)
WINDOWS_IP:1234/v1/models    → LM Studio (new, v0.9.9.2)
```

**Safe run defaults after installation:**

| Condition | System behavior |
|---|---|
| LM Studio running with Gemma 4 | Detected → `lmstudio_detected: true` in routing state |
| Qwen 27B also loaded | Qwen 27B wins (priority 15 < 16) — Gemma 4 is secondary |
| Only Gemma 4 loaded | Gemma 4 used for `general / coding / executor / subagent / fallback` roles |
| LM Studio not running | `lmstudio_detected: false` — falls back to Ollama or Mac |
| Neither Ollama nor LM Studio | Mac-only degraded mode |

The system **does not auto-switch** your primary model. Qwen 27B remains primary at priority 15.
Gemma 4 fills in when Qwen 27B is absent or for roles it doesn't cover.

---

## Roles

```yaml
roles: [general, coding, executor, subagent, fallback]
priority: 16   # secondary to Qwen 27B (priority 15)
```

Gemma 4 26B A4B is well-suited for:
- General chat and instruction following
- Code generation and review
- Executor / subagent tasks in the ultrathink 7-agent network
- Fallback when the primary Windows model is unavailable

---

## Fallback Chain Position

```
LM Studio Win — Qwen 27B (priority 15, gpu_offload=40, primary)
  ↓ not loaded / unavailable
LM Studio Win — Gemma 4 26B (priority 16, gpu_offload=35, this model)
  ↓ LM Studio Win offline
LM Studio Mac (port 1234) — Qwen 9B MLX-4bit (orchestrator/validator)
  ↓ Mac LM Studio unreachable
Ollama Win (port 11434) — qwen3.5-35b-a3b-q4 (legacy fallback)
  ↓ all local backends down
Cloud (Perplexity → cost_guard check)
```

---

## Sync Contract

This file is cross-referenced by:
- `hardware/SKILL.md` → `recommended_models` for `win-rtx3080`
- `config/models.yml` → `gemma-4-26B-A4B-it-Q4_K_M` entry
- `agent_launcher.py` → `WINDOWS_LMS_MODEL` default, `check_lmstudio_worker()`
- `scripts/check_docs_sync.py` → validates SKILL.md ↔ models.yml sync
