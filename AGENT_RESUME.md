# Perpetua-Tools — Agent Resume Guide

**Repo:** diazMelgarejo/Perpetua-Tools
**Branch:** `main`
**Last updated:** 2026-04-20

## What this repo is
Multi-agent orchestration framework — routes tasks across local LM Studio models (Mac + Win), Perplexity API, and Claude API. Local-first, privacy-aware, budget-gated.

## Key entry points
- `agent_launcher.py` — spawns agents by role
- `config/routing.yml` — task_type → role mapping
- `config/models.yml` — model registry (IPs auto-patched by discover.py)
- `config/devices.yml` — hardware profiles (IPs auto-patched by discover.py)

## LM Studio (auto-discovered)
IPs managed by `~/.openclaw/scripts/discover.py`. Never hardcode IPs.
Use env vars from `.env.lmstudio`: `LM_STUDIO_MAC_ENDPOINT`, `LM_STUDIO_WIN_ENDPOINTS`.

## Quick start for a new agent
```bash
python3 ~/.openclaw/scripts/discover.py --status
source .env && source .env.lmstudio
python agent_launcher.py --list-agents
```

## Claude Code automation
- SessionStart: discovers endpoints + syncs instincts
- PostToolUse(*.py): ruff lint + pytest smoke
- Skills: `/agent-run`, `model-routing-check` (Claude-only)
- Subagent: `api-validator`
