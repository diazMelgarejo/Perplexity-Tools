# LM Studio Auto-Discovery & Three-Repo Claude Code Automation

**Date:** 2026-04-20  
**Repos:** AlphaClaw (`feature/MacOS-post-install`) · Perpetua-Tools (`main`) · orama-system (`main`)  
**Hub:** `~/.openclaw/` (OpenClaw user-level state store)  
**Status:** Approved design — awaiting implementation plan

---

## 1. Problem Statement

LM Studio endpoints change (DHCP, travel, new hardware). Currently four separate
config locations each hold a stale IP independently:

| File | Stale Mac IP | Stale Win IP |
|---|---|---|
| `~/.openclaw/openclaw.json` | `192.168.1.147` | `192.168.254.108` |
| `Perpetua-Tools/config/devices.yml` | `192.168.254.103` | `192.168.254.100` |
| `Perpetua-Tools/.env.example` | `localhost` | `192.168.254.108` |
| `orama-system/.env.example` | `localhost` | `192.168.254.108` |

Live endpoints confirmed: Mac `192.168.254.107:1234` · Win `192.168.254.101:1234`.  
Both nodes currently serve identical 5 models (LM Link active).

---

## 2. Goals

1. **Auto-discover** live LM Studio endpoints on every Claude Code session start
2. **Idempotent** — if nothing changed, write nothing
3. **OpenClaw-master** — `openclaw.json` is authoritative; all repo configs derive from it
4. **Repo independence** — each repo can resume without the others; degraded, not broken
5. **Disaster recovery** — four ordered fallback tiers; always know which tier is active
6. **Three-repo Claude Code automation** — hooks, skills, and subagents per-repo role
7. **Sync all changes** — every config and automation file pushed to GitHub

---

## 3. Architecture

```
[Claude Code SessionStart — any of the 3 repos]
         │
         ▼
scripts/discover-lm-studio.sh   (Layer B — per-repo shell gate)
         │
         ├─ ~/.openclaw/state/discovery.json timestamp < 5 min? → EXIT 0 (gossip fresh)
         │
         └─ stale/missing → acquire ~/.openclaw/state/.discover.lock
                  │
                  ▼
         ~/.openclaw/scripts/discover.py   (Layer A — Python hub)
                  │
                  ├─ Probe localhost:1234          → mac_models, mac_ip
                  ├─ Scan 192.168.254.0/24:1234   → win_ip, win_models  (async, 200ms)
                  ├─ Hash {mac_ip+win_ip+models}
                  │
                  ├─ Hash unchanged? → release lock, EXIT 0
                  │
                  └─ Hash changed → SNAPSHOT current state → UPDATE PIPELINE
                           │
                           ├─ 1. Backup ~/.openclaw/state/backups/YYYY-MM-DD_HH-MM.json
                           ├─ 2. Write ~/.openclaw/state/last_discovery.json
                           ├─ 3. Patch ~/.openclaw/openclaw.json  (providers baseUrls + models)
                           ├─ 4. Patch Perpetua-Tools/config/devices.yml  (lan_ip fields)
                           ├─ 5. Patch Perpetua-Tools/config/models.yml   (host defaults)
                           ├─ 6. Write .env.lmstudio → each repo root
                           └─ 7. Write ~/.openclaw/state/recovery_source.txt = "tier1"
```

---

## 4. Idempotency Guarantees

| Condition | Action | Writes |
|---|---|---|
| Gossip JSON < 5 min old | Shell exits 0 | None |
| Gossip stale, hash matches | Python exits 0 after hash check | None |
| Hash changed | Full update pipeline | Snapshot + 6 targets |
| One endpoint unreachable | Update only the reachable endpoint; preserve last-good for the other | Partial |
| Both endpoints unreachable | Fall to recovery tier 2; no writes to config | None |
| `.discover.lock` held | Wait up to 10 s, then read fresh gossip and exit | None |

**YAML patching rule:** Use `ruamel.yaml` (preserves comments, ordering, formatting).
Never rewrite a YAML file wholesale — only update the specific fields that changed.

---

## 5. Disaster Recovery Tiers

```
Tier 1 — Fresh discovery        (live probe of /v1/models endpoints)
     ↓ all endpoints unreachable
Tier 2 — Last known good        (~/.openclaw/state/last_discovery.json)
     ↓ file missing or JSON corrupt
Tier 3 — Versioned backup       (~/.openclaw/state/backups/ — newest file wins)
     ↓ backups/ empty
Tier 4 — Named profiles         (~/.openclaw/profiles/{lan-full,mac-only,win-only}.json)
     ↓ (always present — shipped by AlphaClaw setup_macos.py, never deleted)
```

`~/.openclaw/state/recovery_source.txt` always records which tier was used.  
On next successful Tier 1 probe, state is re-established and a new backup is written.

**Backup retention:** 30 snapshots max. The 31st file automatically deletes the oldest. Files older than 30 days are **archived** (moved to `~/.openclaw/state/archive/`) not deleted — they remain recoverable. `discover.py --prune` triggers manually if needed.

**Restore commands** (callable from any repo or terminal):

```bash
~/.openclaw/scripts/discover.py --restore latest
~/.openclaw/scripts/discover.py --restore 2026-04-20
~/.openclaw/scripts/discover.py --restore profile:lan-full
~/.openclaw/scripts/discover.py --restore profile:mac-only
~/.openclaw/scripts/discover.py --force          # bypass 5-min gossip, re-probe now
python3 ~/.openclaw/scripts/discover.py --status         # show current tier + endpoint health, move from AlphaClaw repo?
```

---

## 6. Data Model

### `~/.openclaw/state/discovery.json`
```json
{
  "schema": 1,
  "timestamp": "2026-04-20T09:00:00Z",
  "hash": "a3f9...",
  "recovery_tier": 1,
  "endpoints": {
    "mac": { "ip": "192.168.254.107", "port": 1234, "reachable": true },
    "win": { "ip": "192.168.254.101", "port": 1234, "reachable": true }
  },
  "models": {
    "mac": ["qwen3.5-9b-mlx", "qwen3.5-27b-claude-4.6-opus-reasoning-distilled-v2",
            "gemma-4-e4b-it", "gemma-4-26b-a4b-it", "text-embedding-nomic-embed-text-v1.5"],
    "win": ["qwen3.5-27b-claude-4.6-opus-reasoning-distilled-v2", "qwen3.5-9b-mlx",
            "gemma-4-26b-a4b-it", "text-embedding-nomic-embed-text-v1.5", "gemma-4-e4b-it"]
  }
}
```

### `.env.lmstudio` (written to each repo root, sourced by `.env`)
```bash
# Auto-generated by ~/.openclaw/scripts/discover.py — do not edit manually
# Last updated: 2026-04-20T09:00:00Z — recovery_tier: 1
LM_STUDIO_MAC_ENDPOINT=http://192.168.254.107:1234
LM_STUDIO_WIN_ENDPOINTS=http://192.168.254.101:1234
LMS_MAC_MODEL=qwen3.5-9b-mlx
LMS_WIN_MODEL=qwen3.5-27b-claude-4.6-opus-reasoning-distilled-v2
LMS_WIN_FALLBACK_MODEL=gemma-4-26b-a4b-it
LM_STUDIO_API_TOKEN=lm-studio
```

---

## 7. File Manifest

### New files (created by this implementation)

```
~/.openclaw/
  scripts/
    discover.py                   # Layer A Python hub (installed by AlphaClaw setup_macos.py)
  state/
    discovery.json                # Gossip state (runtime, not committed)
    last_discovery.json           # Last-good snapshot
    recovery_source.txt           # Which tier is active
    .discover.lock                # File lock (runtime, not committed)
    backups/                      # Timestamped snapshots (runtime, not committed)
  profiles/
    lan-full.json                 # Default: both Mac + Win
    mac-only.json                 # Fallback: Mac only
    win-only.json                 # Fallback: Win only

AlphaClaw/  (branch: feature/MacOS-post-install)
  scripts/
    discover-lm-studio.sh         # Layer B shell gate (new)
  .claude/
    settings.json                 # Updated: add PostToolUse(npm test), PreToolUse(lock guard)
    skills/
      macos-port-status/SKILL.md  # Branch sync status + test health
      cherry-pick-down/SKILL.md   # Safe cherry-pick with upstream-compat check
    agents/
      upstream-compat-reviewer.md # Pre-cherry-pick platform-agnostic check
  setup_macos.py                  # Updated: installs discover.py to ~/.openclaw/scripts/

Perpetua-Tools/  (branch: main)
  scripts/
    discover-lm-studio.sh         # Layer B shell gate (new)
  config/
    devices.yml                   # Updated: lan_ip .103→.107, .100→.101
    models.yml                    # Updated: host defaults updated; gemma-4-e4b-it added
  .env.lmstudio                   # Auto-generated (gitignored)
  .claude/
    settings.json                 # Updated: add PostToolUse(ruff), PostToolUse(pytest)
    skills/
      agent-run/SKILL.md          # Launch orchestrator with env validation
      model-routing-check/SKILL.md # Verify LM Studio endpoints before agent run
    agents/
      api-validator.md            # Validate Perplexity + LM Studio API response schemas

orama-system/  (branch: main)
  scripts/
    discover-lm-studio.sh         # Layer B shell gate (new)
  .env.lmstudio                   # Auto-generated (gitignored)
  .claude/
    settings.json                 # Updated: add Stop(lessons check), PostToolUse(ruff/mypy)
    skills/
      ecc-sync/SKILL.md           # Promoted from commands/ecc-sync.md
      agent-methodology/SKILL.md  # orama 5-stage methodology (Claude-only)
    agents/
      crystallizer.md             # Promoted from wrong/ reference implementation
```

---

## 8. Claude Code Automations Per Repo

### AlphaClaw — `feature/MacOS-post-install`

**Hooks** (`.claude/settings.json`):
```json
{
  "hooks": {
    "SessionStart": [{ "hooks": [
      { "type": "command", "command": "bash scripts/discover-lm-studio.sh", "async": true },
      { "type": "command", "command": "git fetch origin pr-4-macos --quiet 2>/dev/null || true", "async": true }
    ]}],
    "PostToolUse": [
      { "matcher": "Edit|Write", "hooks": [
        { "type": "command", "command": "npm test --reporter=dot 2>&1 | tail -8 || true" }
      ]},
      { "matcher": "Edit", "hooks": [
        { "type": "command", "command": "node -e \"const p=process.env.CLAUDE_TOOL_INPUT_FILE_PATH||''; if(p.includes('package-lock.json')){console.error('⛔ Direct edits to package-lock.json are blocked — run npm install instead');process.exit(1)}\"" }
      ]}
    ]
  }
}
```

**Skills:** `macos-port-status` (user), `cherry-pick-down` (user)  
**Subagent:** `upstream-compat-reviewer`

---

### Perpetua-Tools — `main`

**Hooks** (`.claude/settings.json`):
```json
{
  "hooks": {
    "SessionStart": [{ "hooks": [
      { "type": "command", "command": "bash scripts/discover-lm-studio.sh",
        "statusMessage": "Discovering LM Studio endpoints...", "async": true },
      { "type": "command", "command": "bash scripts/sync-companion-instincts.sh 2>/dev/null || true", "async": true }
    ]}],
    "PostToolUse": [
      { "matcher": "Edit|Write", "hooks": [
        { "type": "command", "command": "file=$(echo $CLAUDE_TOOL_INPUT | python3 -c 'import sys,json;print(json.load(sys.stdin).get(\"file_path\",\"\"))' 2>/dev/null); [[ $file == *.py ]] && ruff check \"$file\" 2>&1 | head -10 || true" }
      ]},
      { "matcher": "Edit|Write", "hooks": [
        { "type": "command", "command": "python -m pytest tests/ -x -q --tb=short 2>&1 | tail -12 || true" }
      ]}
    ]
  }
}
```

**Skills:** `agent-run` (user), `model-routing-check` (Claude)  
**Subagent:** `api-validator`

---

### orama-system — `main`

**Hooks** (`.claude/settings.json`):
```json
{
  "hooks": {
    "SessionStart": [{ "hooks": [
      { "type": "command", "command": "bash scripts/discover-lm-studio.sh",
        "statusMessage": "Discovering LM Studio endpoints...", "async": true },
      { "type": "command", "command": "bash scripts/sync-companion-instincts.sh 2>/dev/null || true", "async": true }
    ]}],
    "PostToolUse": [
      { "matcher": "Edit|Write", "hooks": [
        { "type": "command", "command": "file=$(echo $CLAUDE_TOOL_INPUT | python3 -c 'import sys,json;print(json.load(sys.stdin).get(\"file_path\",\"\"))' 2>/dev/null); [[ $file == *.py ]] && ruff check \"$file\" 2>&1 | head -10 || true" }
      ]}
    ],
    "Stop": [{ "hooks": [
      { "type": "command", "command": "bash -c 'git diff --name-only HEAD -- .claude/lessons/ 2>/dev/null | grep -q . || echo \"⚠️  LESSONS.md not updated — CLAUDE.md requires a write-back before ending session.\"'" }
    ]}]
  }
}
```

**Skills:** `ecc-sync` (user), `agent-methodology` (Claude-only)  
**Subagent:** `crystallizer`

---

## 9. Sync Strategy (GitHub)

All files above are pushed to their respective repos via `gh` API / git commits.

**Commit order (dependency-first):**
1. `~/.openclaw/scripts/discover.py` — install locally via `setup_macos.py` (AlphaClaw)
2. **AlphaClaw** `feature/MacOS-post-install` — setup_macos.py update + shell gate + hooks + skills
3. **Perpetua-Tools** `main` — config YML patches + shell gate + hooks + skills (depends on discover.py being installed)
4. **orama-system** `main` — shell gate + hooks + promoted skills (depends on discover.py being installed)

**Pre-commit:** Verify `.env.lmstudio` is in `.gitignore` of all 3 repos before pushing.

**Commit message convention:** `chore(automation): <what> [skip ci]` for hook/skill changes;  
`fix(config): update LM Studio endpoints <mac-ip>/<win-ip>` for IP/model updates.

---

## 10. Invariants (must hold at all times)

1. `~/.openclaw/scripts/discover.py --status` always exits 0 and reports a tier, even if both nodes are down; GET from AlphaClaw repo if not in this repo
2. `.env.lmstudio` is always gitignored in all 3 repos
3. YAML files are never fully rewritten — only the changed fields are patched
4. Backup count never exceeds 30; the 31st triggers auto-deletion of the oldest. Files older than 30 days are archived to `~/.openclaw/state/archive/`, not deleted
5. `pr-4-macos` and upstream PR branches in AlphaClaw are never touched by automation
6. LESSONS.md in orama-system must be written once per session before `Stop` fires
7. All hooks are `async: true` at SessionStart so they never block the first prompt

---

## 11. Out of Scope

- Ollama auto-discovery (separate concern; Ollama uses mDNS and is more stable)
- Redis coordination (single-instance LAN; file locks are sufficient)
- Windows-side Claude Code setup (Claude Code runs on Mac only in this design)
- Automatic git push after discovery updates (user commits config changes explicitly)
