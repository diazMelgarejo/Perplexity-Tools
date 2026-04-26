---
name: alphaclaw-session
version: 1.0.0
description: Commandeer AlphaClaw/OpenClaw runtime defaults. Set environment profiles, backup/restore sessions, enumerate live agents. Run when starting any OpenClaw-dependent session.
user-invocable: true
---

# AlphaClaw Session — v1.0.0

Encodes durable knowledge about the AlphaClaw/OpenClaw environment so you never have to figure it out again each time.

---

## Quick Start

```bash
# 1. Check what tier we're on right now
python3 ~/.openclaw/scripts/discover.py --status

# 2. Verify gateway is live
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer d3aea7fea7ba51a1dff69b84662ae97d53dd3c2bcb182781" \
  http://localhost:18789/health

# 3. Back up current session state
python3 ~/.openclaw/scripts/discover.py --force && \
  cp ~/.openclaw/state/discovery.json \
     ~/.openclaw/state/backups/session-$(date +%Y%m%d-%H%M%S).json
```

---

## Environment Profiles

Choose the profile that matches which nodes are reachable right now.

### `home` — Both nodes live (Tier 1)

| Item | Value |
|------|-------|
| Mac LM Studio | `localhost:1234` |
| Win LM Studio | `192.168.254.101:1234` |
| Active agents | all 6: main, mac-researcher, win-researcher, orchestrator, coder, autoresearcher |
| Max parallel | 4 (2 per node, memory-bound) |
| Primary model | `lmstudio-mac/Qwen3.5-9B-MLX-4bit` |
| Heavy model | `lmstudio-win/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2` |

```bash
# Confirm tier 1 live
python3 ~/.openclaw/scripts/discover.py --status | head -4
# Expected:
# Tier:    1
#   mac: ✅ localhost:1234 — N models
#   win: ✅ 192.168.254.101:1234 — N models
```

### `mac-only` — Mac node only (Tier 2)

| Item | Value |
|------|-------|
| Mac LM Studio | `localhost:1234` |
| Ollama fallback | `127.0.0.1:11434` |
| Active agents | main, mac-researcher, orchestrator, autoresearcher |
| Degraded | win-researcher, coder (offline) |
| Max parallel | 2 |

### `cloud-only` — No local nodes (Tier 3)

| Item | Value |
|------|-------|
| Primary | gemini-main (`OPENCLAW_MODELS_PROVIDERS_GEMINI_MAIN_APIKEY` env required) |
| Fallback | gemini-fallback (hardcoded key in openclaw.json) |
| Active agents | all 6 (model auto-swaps to Gemini) |
| Cost | non-zero — monitor usage-tracker plugin |

```bash
# Check usage tracker when on cloud
# usage-tracker plugin logs to ~/.openclaw/logs/usage/
```

### `win-only` — Win node only (Tier 4)

| Item | Value |
|------|-------|
| Win LM Studio | `192.168.254.101:1234` |
| Active agents | win-researcher, coder, autoresearcher |
| Degraded | main, mac-researcher, orchestrator |

---

## OpenClaw Agent Map

| Agent ID | Model | Workspace | Tool Profile |
|----------|-------|-----------|-------------|
| `main` *(default)* | lmstudio-mac/Qwen3.5-9B-MLX-4bit | `~/.alphaclaw/.openclaw/workspace` | default |
| `mac-researcher` | lmstudio-mac/Qwen3.5-9B-MLX-4bit | `~/.openclaw/agents/mac-researcher` | default |
| `win-researcher` | lmstudio-win/Qwen3.5-27B-…-v2 | `~/.openclaw/agents/win-researcher` | coding |
| `orchestrator` | lmstudio-mac/Qwen3.5-9B-MLX-4bit | `~/.openclaw/agents/orchestrator` | default |
| `coder` | lmstudio-win/Qwen3.5-27B-…-v2 | `~/.openclaw/agents/coder` | coding |
| `autoresearcher` | lmstudio-win/Qwen3.5-27B-…-v2 | `~/autoresearch` | default |

Fallback chain for `main` agent: Gemini 3.1 Pro Preview → Gemini 3 Flash → Gemini 3.1 Flash Lite → Gemini 2.5 Flash → Gemini 2.5 Flash Lite.

---

## Session Backup / Restore

```bash
# Save now
python3 ~/.openclaw/scripts/discover.py --force
cp ~/.openclaw/state/discovery.json \
   ~/.openclaw/state/backups/session-$(date +%Y%m%d-%H%M%S).json

# List available backups
ls -lt ~/.openclaw/state/backups/ | head -10

# Restore latest
python3 ~/.openclaw/scripts/discover.py --restore latest

# Restore by date
python3 ~/.openclaw/scripts/discover.py --restore 2026-04-25

# Restore named profile
python3 ~/.openclaw/scripts/discover.py --restore profile:lan-full
python3 ~/.openclaw/scripts/discover.py --restore profile:mac-only
```

---

## Gateway

| Item | Value |
|------|-------|
| Address | `http://localhost:18789` |
| Bind | loopback only (not reachable from remote) |
| Auth | `Authorization: Bearer d3aea7fea7ba51a1dff69b84662ae97d53dd3c2bcb182781` |
| Mode | token |

```bash
# Health check
curl -s -H "Authorization: Bearer d3aea7fea7ba51a1dff69b84662ae97d53dd3c2bcb182781" \
  http://localhost:18789/health
```

---

## Key Paths

| Path | Purpose |
|------|---------|
| `~/.openclaw/openclaw.json` | Master config — providers, agents, gateway |
| `~/.openclaw/state/discovery.json` | Live gossip (5-min TTL) |
| `~/.openclaw/state/last_discovery.json` | Last-good snapshot |
| `~/.openclaw/state/recovery_source.txt` | Active tier (tier1–tier4) |
| `~/.openclaw/state/backups/` | Session snapshots (≤30 kept; older → archive) |
| `~/.openclaw/profiles/lan-full.json` | Tier-4 fallback profile |
| `~/.openclaw/scripts/discover.py` | Discovery script (TTL 5 min, `--force` to bypass) |

---

## MCP Servers (registered in openclaw.json)

| Server | Command | Purpose |
|--------|---------|---------|
| gemini-cli | `npx -y gemini-mcp-tool@latest` | Gemini as large-context reader |
| ai-cli-mcp | `npx -y ai-cli-mcp@latest` | Worker pool (MCP orchestration) |

---

## Channels & Plugins

**Telegram notifications:** enabled. Bot token in `openclaw.json → channels.telegram.botToken`.

**Plugins active:** `google`, `telegram`, `usage-tracker`
Local load path: `AlphaClaw/lib/plugin/usage-tracker`

---

## Diagnostics (OTEL)

OpenTelemetry is enabled: traces, metrics, and logs are all active.

```bash
# Check diagnostics config
cat ~/.openclaw/openclaw.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d['diagnostics'], indent=2))"
```

---

## Skill Version Guard

```python
BUNDLED = '1.0.0'
# Scripts/agents updating this file: skip write if installed version >= BUNDLED
def _ver(path):
    for line in open(path):
        if line.strip().startswith("version:"):
            return tuple(int(x) for x in line.split(":",1)[1].strip().strip('"\'').split("."))
    return (0, 0, 0)
if _ver(".claude/skills/alphaclaw-session/SKILL.md") >= tuple(int(x) for x in BUNDLED.split(".")):
    print("skip — already at", BUNDLED)
```
