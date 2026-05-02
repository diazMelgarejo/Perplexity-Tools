# openclaw Setup & Troubleshooting

Canonical reference for the openclaw gateway on this machine (Mac M2 Pro, Apple Silicon).

---

## Architecture

```
LaunchAgent (ai.openclaw.gateway)
    │
    ├── /opt/homebrew/bin/node  → ~/.nvm/versions/node/v24.14.1/bin/node
    ├── dist/index.js  (openclaw global npm install)
    ├── port 18789 (LAN: 0.0.0.0, dashboard: http://192.168.1.147:18789/)
    └── 4 plugins: memory-core, telegram, usage-tracker, whatsapp
```

The AlphaClaw → Perpetua-Tools → orama-system layering means:
- openclaw is the gateway daemon (AlphaClaw layer 1)
- Perpetua-Tools portal and orama API are the consumers (layers 2 + 3)

---

## Channel Status

| Channel | Status | Notes |
|---------|--------|-------|
| Telegram | ✅ Connected | Bot: @a1phaCLawbot (token in `channels.telegram.botToken`) |
| WhatsApp | ⏳ Needs QR pairing | Plugin enabled, Baileys installed — run login once |

### Telegram notes
- Occasional `getMe` fetch timeouts (2500–9994ms) are network jitter, not config errors
- Polling stalls (getUpdates stuck for 400+s) trigger auto-restart; messages are not lost, only delayed

### WhatsApp setup (one-time)
The WhatsApp plugin uses **Baileys** (`@whiskeysockets/baileys` — WhatsApp Web protocol via QR code).

To link your phone:
```bash
# In your terminal (interactive — needs QR code scan)
openclaw channels login --channel whatsapp
```
Scan the displayed QR code with WhatsApp → Linked Devices → Link a Device.

The bot will connect as your personal WhatsApp account. Your number (`+14159419166`) is set as the command owner.

**Why "whatsapp notification failed" before**: the plugin was in the `plugins.allow` list but the Baileys runtime hadn't loaded yet because the plugin wasn't in the allowlist. Fixed 2026-05-02: added `whatsapp` to `plugins.allow`, added `channels.whatsapp` config, Baileys auto-installs on gateway start.

**Format**: `whatsapp:+14159419166` (with `+`, E.164 format). The `+` IS required.

---

## Command Owner

Controls who can run privileged commands (`/config`, `/diagnostics`, exec approvals, etc.).

```bash
# Current value
openclaw config get commands.ownerAllowFrom
# → ["whatsapp:+14159419166"]

# To change (example — telegram user ID)
openclaw config set commands.ownerAllowFrom '["telegram:123456789"]'
```

---

## Plugin Config: usage-tracker

The `usage-tracker` plugin is the AlphaClaw dev build at:
`~/Documents/Terminal xCode/claude/OpenClaw/AlphaClaw/lib/plugin/usage-tracker`

The `llm_output` hook requires explicit access permission. Set via:
```bash
openclaw config set "plugins.entries.usage-tracker.hooks.allowConversationAccess" true
```
This is already applied (as of 2026-05-02).

The `activation.onStartup` key from doctor warnings does **not** exist in the config schema — ignore it.

---

## Gateway Startup Issues After Update

After `openclaw update`, the following sequence is normal and not a bug:

1. `"Completion cache update failed: ETIMEDOUT"` — completion regeneration subprocess timed out during update. Fix: run `openclaw completion --write-state --yes` manually.
2. `"Gateway version mismatch: expected X, running gateway reported unavailable"` — transient during restart. Wait 5–10 seconds; gateway starts normally.
3. `"Gateway port 18789 status: free"` — same transient; gateway is mid-restart.

### Regenerate completions manually
```bash
openclaw completion --write-state --yes
```
Files land in `~/.openclaw/completions/` and are sourced by `~/.zshrc`.

---

## Node Path Stability

The LaunchAgent uses `/opt/homebrew/bin/node` after `openclaw doctor --fix`. This is a symlink to the current NVM v24.14.1 binary:
```
/opt/homebrew/bin/node → ~/.nvm/versions/node/v24.14.1/bin/node
```

**Risk**: if the user runs `nvm use 22` and then uninstalls v24, the symlink breaks.
**Mitigation**: don't uninstall v24 without updating the symlink. A future improvement would be installing node via `brew install node` to get a truly stable path.

---

## Key Config Paths

| Setting | Location |
|---------|---------|
| Main config | `~/.openclaw/openclaw.json` |
| Gateway plist | `~/Library/LaunchAgents/ai.openclaw.gateway.plist` |
| Service env | `~/.openclaw/service-env/ai.openclaw.gateway.env` |
| Shell completions | `~/.openclaw/completions/openclaw.zsh` |
| Gateway logs | `~/.openclaw/logs/gateway.log` (and `.err.log`) |
| Runtime log | `/tmp/openclaw/openclaw-YYYY-MM-DD.log` |

---

## Useful Commands

```bash
# Status
openclaw gateway status --deep
openclaw channels status --deep
openclaw doctor

# Repair
openclaw doctor --fix
openclaw completion --write-state --yes
openclaw gateway restart

# Debug
openclaw channels logs
tail -f ~/.openclaw/logs/gateway.err.log
```
