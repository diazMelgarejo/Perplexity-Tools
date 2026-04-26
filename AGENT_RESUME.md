# Perpetua-Tools — Agent Resume

### Hardware Safety & Model Affinity (2026-04-26)

**Canonical policy:** `config/model_hardware_policy.yml`

Hard rules — never override:
- Windows-only (NEVER_MAC): `gemma-4-26b-a4b-it`, `gemma-4-26B-A4B-it-Q4_K_M`,
  `qwen3.5-27b-claude-4.6-opus-reasoning-distilled-v2`
- Mac-only (NEVER_WIN): `gemma-4-e4b-it`, `qwen3.5-9b-mlx`, `qwen3.5-9b-mlx-4bit`

Runtime validation fires at three layers (L1 discover, L2 manager/launcher,
L3 API). Any `HardwareAffinityError` must escalate to Controller — never
silently fallback to unsafe hardware.

If you are an AI agent reading this: do NOT add unverified model IDs to any
policy file or config. Confirm with `discover.py --status` on actual hardware
first. Known hallucinations removed: `qwen3-coder-14b` and `gemma4:e4b`.

---

## Status: COMPLETE ✅ (2026-04-20)

Branch: `main`

All Claude Code automation from the LM Studio Auto-Discovery plan has been implemented.

---

## What Was Done

### Config Updates

| File | Change | Status |
|------|--------|--------|
| `config/devices.yml` | mac-studio lan_ip .103→.107, win-rtx3080 .100→.101 | ✅ |
| `config/models.yml` | LM_STUDIO_MAC_ENDPOINT default → localhost, WIN → .101 | ✅ |
| `.gitignore` | `.env.lmstudio` added | ✅ |

### .claude/ Automations

| Type | File | Status |
|------|------|--------|
| Hook: SessionStart | `.claude/settings.json` | ✅ discover-lm-studio.sh (async) + sync-companion-instincts |
| Hook: PostToolUse | `.claude/settings.json` | ✅ ruff check on .py + pytest tests/ |
| Skill | `.claude/skills/agent-run/SKILL.md` | ✅ env validation before agent launch |
| Skill | `.claude/skills/model-routing-check/SKILL.md` | ✅ Claude-only endpoint check |
| Subagent | `.claude/agents/api-validator.md` | ✅ Perplexity + LM Studio schema validation |

### Shell Gate

`scripts/discover-lm-studio.sh` — Layer B gossip gate (5-min TTL, delegates to ~/.openclaw/scripts/discover.py)

### Live Endpoints (auto-updated by discover.py)

```
Mac LM Studio: http://localhost:1234
Win LM Studio: http://192.168.254.109:1234
LMS_WIN_MODEL: qwen3.5-27b-claude-4.6-opus-reasoning-distilled-v2
LMS_WIN_FALLBACK_MODEL: gemma-4-26b-a4b-it
```

## How to Resume

```bash
# Check LM Studio routing before running agents
/model-routing-check

# Launch orchestrator with env validation
/agent-run

# Validate API response schemas
# (subagent: api-validator)

# Force-refresh endpoints
python3 ~/.openclaw/scripts/discover.py --force

# Check status
python3 ~/.openclaw/scripts/discover.py --status
```
