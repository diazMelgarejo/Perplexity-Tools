---
name: alphaclaw-session
version: 1.2.0
description: Commandeer AlphaClaw/OpenClaw runtime defaults. Set environment profiles, backup/restore sessions, enumerate live agents, self-heal connectivity issues. Run when starting any OpenClaw-dependent session.
user-invocable: true
---

# AlphaClaw Session — v1.2.0

Encodes durable knowledge about the AlphaClaw/OpenClaw environment so you never have to figure it out again each time.

**Confirmed by live matrix test 2026-04-27 — all 6 agents pass.**

---

## Critical Constants (do not guess, do not hardcode)

| Item | Value | Source |
|------|-------|--------|
| Mac LM Studio | `localhost:1234` | self-probe always via localhost |
| Win LM Studio | `192.168.254.103:1234` | from `~/.openclaw/openclaw.json → models.providers.lmstudio-win.baseUrl` |
| Mac model ID | `qwen3.5-9b-mlx` | **all lowercase, no `-4bit` suffix** |
| Win model ID | `qwen3.5-27b-claude-4.6-opus-reasoning-distilled-v2` | **all lowercase** |
| OpenClaw gateway | `http://localhost:18789` | loopback only |
| Bearer token | `d3aea7fea7ba51a1dff69b84662ae97d53dd3c2bcb182781` | from openclaw.json |
| openclaw CLI Node | `/Users/lawrencecyremelgarejo/.nvm/versions/node/v24.14.1/bin/openclaw` | Node v14 is too old |
| Agent timeout | 300s (300000ms) | reasoning models need long budget |

---

## Quick Start

```bash
# 1. Check what tier we're on right now
python3 ~/.openclaw/scripts/discover.py --status

# 2. Run an agent turn (use full openclaw path — Node v24 required)
/Users/lawrencecyremelgarejo/.nvm/versions/node/v24.14.1/bin/node \
  /Users/lawrencecyremelgarejo/.nvm/versions/node/v24.14.1/bin/openclaw \
  agent --agent main --session-id test-$(date +%s) \
  --message "status check" --thinking off --json --timeout 300

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
| Win LM Studio | `192.168.254.103:1234` |
| Active agents | all 6: main, mac-researcher, win-researcher, orchestrator, coder, autoresearcher |
| Max parallel | 4 (2 per node, memory-bound) |
| Primary model | `lmstudio-mac/qwen3.5-9b-mlx` |
| Heavy model | `lmstudio-win/qwen3.5-27b-claude-4.6-opus-reasoning-distilled-v2` |

```bash
# Confirm tier 1 live
python3 ~/.openclaw/scripts/discover.py --status | head -4
# Expected:
# Tier:    1
#   mac: ✅ localhost:1234 — N models
#   win: ✅ 192.168.254.103:1234 — N models
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
| Win LM Studio | `192.168.254.103:1234` |
| Active agents | win-researcher, coder, autoresearcher |
| Degraded | main, mac-researcher, orchestrator |

---

## DO's & DON'Ts

### DO ✅

- Run `discover.py --status` before starting any multi-agent session
- Use `--force` flag after any IP change or when nodes are suspected offline
- Use `localhost:1234` for Mac self-referencing — always
- Use `192.168.254.103:1234` for Win (from Mac); `192.168.254.105:1234` for Mac (from Win)
- Include `Authorization: Bearer ...` on every gateway request (loopback, no TLS)
- Monitor usage-tracker plugin logs when on Tier 3 (cloud) — costs are non-zero
- Check `discover.py --status` FIRST when any agent call fails unexpectedly
- Keep `~/.openclaw/openclaw.json` as the single source of truth for endpoints
- Run `discover.py --force` after updating openclaw.json to refresh stale state
- Use `git mv` when renaming tracked files (not just `mv`) to preserve history

### DON'T ❌

- DON'T use IPs `.101`, `.107`, `.109` — all stale; Win = `.103`, Mac LAN = `.105`
- DON'T hardcode IPs in PT/orama scripts — always derive from `discover.py` or openclaw.json
- DON'T run `discover.py` without `--force` when debugging connectivity (5-min TTL hides stale state)
- DON'T `require()` AlphaClaw internals from PT or orama — CLI + HTTP only
- DON'T load models in parallel on Win — GPU loads ONE model at a time (RTX 3080 constraint)
- DON'T skip `is_gpu_idle()` before dispatching heavy tasks to `coder` or `win-researcher`
- DON'T use `.105` from Mac itself — LAN IPs are for cross-node calls only
- DON'T `git mv` a directory with no tracked files — use `rm -rf` for empty artifact dirs
- DON'T merge Gemini CLI commits — bad author identities (`<forbidden>`, `nimbosa`)
- DON'T skip session state backup before major branch operations

---

## Self-Healing Procedures

### Win node shows offline (drops to Tier 2)

```bash
# Step 1: Ping Win to confirm reachability
ping -c 1 192.168.254.103
# → If timeout: Win is off or DHCP reassigned IP

# Step 2: If IP may have changed — find new lease from router or Win machine
# Then update EVERYWHERE:
#   ~/.openclaw/openclaw.json  → models.providers.lmstudio-win.baseUrl
#   Perpetua-Tools/config/devices.yml  → win.lan_ip
#   Perpetua-Tools/.env.local  → WINDOWS_IP
# Pattern:
sed -i '' 's|192.168.254.OLD|192.168.254.NEW|g' \
  ~/.openclaw/openclaw.json \
  "/path/to/Perpetua-Tools/config/devices.yml"

# Step 3: Force-refresh discovery
python3 ~/.openclaw/scripts/discover.py --force

# Step 4: Verify Tier 1 restored
python3 ~/.openclaw/scripts/discover.py --status | head -4
```

### Gateway unreachable (http_code 000 = connection refused)

```bash
# Step 1: Check if AlphaClaw process is running
ps aux | grep -i alphaclaw | grep -v grep

# Step 2: If not running, start it
cd ~/.alphaclaw && node alphaclaw.js
# Or: bash ~/.alphaclaw/start.sh

# Step 3: Re-verify gateway
curl -s \
  -H "Authorization: Bearer d3aea7fea7ba51a1dff69b84662ae97d53dd3c2bcb182781" \
  http://localhost:18789/health
# Expected: {"status":"ok"} or similar (any non-000 response)
```

### Model ID mismatch (agent fails to load model)

OpenClaw agents ref mixed-case model IDs (e.g., `Qwen3.5-27B-…`); `discover.py` writes lowercase to providers.

**Test:** Dispatch a task to `coder` agent and check gateway logs. If it errors on model lookup:
```bash
# Fix: lowercase the agent model.primary refs to match provider IDs
python3 - <<'EOF'
import json, pathlib, re

cfg_path = pathlib.Path.home() / '.openclaw/openclaw.json'
cfg = json.loads(cfg_path.read_text())

for agent in cfg['agents']['list']:
    primary = agent.get('model', {}).get('primary', '')
    if '/' in primary:
        provider, model_id = primary.split('/', 1)
        agent['model']['primary'] = f"{provider}/{model_id.lower()}"

cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
print("Agent model IDs lowercased — restart OpenClaw gateway")
EOF
```
Document result in `docs/LESSONS.md` with which approach worked.

### Stale discovery / wrong tier reported

```bash
# Force full re-discovery (bypasses 5-min TTL)
python3 ~/.openclaw/scripts/discover.py --force

# If still wrong, check openclaw.json baseUrl entries match actual IPs
python3 -c "
import json, pathlib
cfg = json.loads(pathlib.Path.home().joinpath('.openclaw/openclaw.json').read_text())
for name, prov in cfg['models']['providers'].items():
    print(name, '->', prov.get('baseUrl', 'N/A'))
"
```

---

## OpenClaw Agent Map (confirmed 2026-04-27 matrix test — all 6 ✅)

| Agent ID | Model (exact ID) | Node | Turn time | Fallback |
|----------|------------------|------|-----------|---------|
| `main` *(default)* | `lmstudio-mac/qwen3.5-9b-mlx` | Mac MLX | ~105–308s | gemini-3-flash |
| `mac-researcher` | `lmstudio-mac/qwen3.5-9b-mlx` | Mac MLX | ~105s | gemini-3-flash |
| `orchestrator` | `lmstudio-mac/qwen3.5-9b-mlx` | Mac MLX | ~102s | gemini-3-flash |
| `win-researcher` | `lmstudio-win/qwen3.5-27b-claude-4.6-opus-reasoning-distilled-v2` | Win RTX | ~130s | gemini-3-flash |
| `coder` | `lmstudio-win/qwen3.5-27b-claude-4.6-opus-reasoning-distilled-v2` | Win RTX | ~107s | gemini-3-flash |
| `autoresearcher` | `lmstudio-win/qwen3.5-27b-claude-4.6-opus-reasoning-distilled-v2` | Win RTX | ~116s | gemini-3-flash |

**Fallback chain** (primary fails → fallback): `gemini-3.1-pro-preview` (429 rate limit) →
`gemini-3-flash-preview` (✅ succeeds on free tier).

**Both models are extended thinking/reasoning models.** They generate `reasoning_content`
before visible output. `text` field is often empty; actual reply is in `reasoning_content`.
Use `--thinking off` to request no thinking (not always honored by embedding runner).

### Dispatching agents

```bash
NODE24=/Users/lawrencecyremelgarejo/.nvm/versions/node/v24.14.1/bin/node
OC=/Users/lawrencecyremelgarejo/.nvm/versions/node/v24.14.1/bin/openclaw

# Single agent turn (fresh session, thinking off, 300s budget)
$NODE24 $OC agent \
  --agent coder \
  --session-id "work-$(date +%s)" \
  --message "Your task here" \
  --thinking off \
  --json \
  --timeout 300

# Check visible reply (reasoning models: text may be empty, use reasoning_content)
# Success is indicated by --json output containing "text" field even if value is ""
```

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
BUNDLED = '1.1.0'
# Scripts/agents updating this file: skip write if installed version >= BUNDLED
def _ver(path):
    for line in open(path):
        if line.strip().startswith("version:"):
            return tuple(int(x) for x in line.split(":",1)[1].strip().strip('"\'').split("."))
    return (0, 0, 0)
if _ver(".claude/skills/alphaclaw-session/SKILL.md") >= tuple(int(x) for x in BUNDLED.split(".")):
    print("skip — already at", BUNDLED)
```
