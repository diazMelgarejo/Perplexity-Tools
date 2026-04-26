# AI Agent Model x Hardware Profile Matrix

Canonical runtime summary for **Perpetua-Tools v0.9.9.7**.

## Primary Local Lanes

| Lane | Primary Model | Backend | Endpoint | Notes |
|---|---|---|---|---|
| Mac orchestrator | `glm-5.1:cloud` | Ollama client | `http://192.168.254.103:11434` | Preferred only when a short live probe succeeds. |
| Mac verifier / orchestrator fallback | `Qwen3.5-9B-MLX-4bit` | LM Studio | `http://192.168.254.103:1234` | Immediate local fallback when GLM is unavailable or rate-limited. |
| Windows heavy coder / executor / autoresearch | `Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2` | LM Studio | `http://192.168.254.100:1234` | Canonical Windows coding lane. |
| Windows coder fallback | `qwen3-coder:14b` | Ollama | `http://192.168.254.100:11434` | Explicit fallback for coding and autoresearch. |
| Shared backup fallback | `qwen3.5:35b-a3b-q4_K_M` | Ollama | `${OLLAMA_HOST}` | Known backup fallback model; keep documented, not primary. |

## Device Profiles

| Device | Default Backend | Alternate Backends | Purpose |
|---|---|---|---|
| `mac-studio` | `ollama` | `lm-studio`, `mlx` | Thin orchestration, validation, presentation. |
| `win-rtx3080` | `lm-studio` | `ollama` | Heavy coding, execution, autoresearch. |
| `shared-ollama-host` | `ollama` | none | Backup fallback host. |
| `cloud` | HTTPS APIs | none | Research, finance, and premium fallback. |

## Task Routing Summary

| Task Type | Preferred Local Route | Fallback Notes |
|---|---|---|
| `default` | `glm-5.1:cloud` on Mac | Falls back to Mac LM Studio, then local backup chain. |
| `coding` | Windows LM Studio Qwen 27B | Falls back to `qwen3-coder:14b`, then other reachable local fallbacks. |
| `autoresearch` | Windows LM Studio Qwen 27B | Falls back to `qwen3-coder:14b`, other reachable LM Studio models, then Mac LM Studio. If no viable local coder backend is reachable, PT returns a user-action stop. |
| `deep_reasoning` | orama bridge | PT still owns hardware selection before orama. |
| `code_analysis` | orama bridge | Local-only orama route; Windows LM Studio remains the preferred local fallback lane after orama. |

## Fallback Chain

1. `glm-5.1:cloud` via Mac Ollama, when the probe succeeds
2. Windows LM Studio `Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2`
3. Mac LM Studio `Qwen3.5-9B-MLX-4bit`
4. Windows Ollama `qwen3-coder:14b`
5. Windows / shared Ollama `qwen3.5:35b-a3b-q4_K_M`
6. Cloud research / premium models, subject to budget and task type
7. Degraded or user-action stop

## Notes

- `qwen3.5:35b-a3b-q4_K_M` remains a supported backup fallback model and should stay documented as such.
- `glm-5` is obsolete here; use `glm-5.1:cloud`.
- `single_agent/SKILL.md` is not the active orama skill surface anymore; use `bin/skills/SKILL.md`.
