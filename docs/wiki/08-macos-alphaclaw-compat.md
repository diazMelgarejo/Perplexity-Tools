# 08. macOS alphaclaw Compatibility — EACCES Fixes + setup_macos.py

**TL;DR:** alphaclaw (`@chrysb/alphaclaw`) was written for Linux/Docker with root access. On macOS it writes to `/usr/local/bin/` and `/etc/cron.d/` which require root. Redirect to `~/.local/bin/` and user crontab. `setup_macos.py` applies these patches idempotently on every boot.

---

## Error → Root Cause Map (2026-04-13)

| Startup error | Root cause | Fix |
|--------------|------------|-----|
| `gog install skipped: Permission denied /usr/local/bin/gog` | `/usr/local/bin/` is `root:wheel` on macOS | Change dest to `~/.local/bin/gog` |
| `Cron setup skipped: ENOENT /etc/cron.d/openclaw-hourly-sync` | `/etc/cron.d/` is Linux-only | macOS: use `crontab -l` user crontab |
| `systemctl shim skipped: EACCES /usr/local/bin/systemctl` | Linux/Docker-only shim | Wrap in `if (os.platform() !== "darwin")` |
| `git auth shim skipped: EACCES /usr/local/bin/git` | git shim dest hardcoded to root-owned path | Change to `~/.local/bin/git` |
| `Gateway timed out after 30s` | gateway exits on JSON schema error (`models` undefined) | Add `models[]` arrays to ollama providers in `openclaw.json` |

---

## Gateway Timeout Diagnosis Sequence

```bash
# 1. Is the port open?
nc -z 127.0.0.1 18789    # if nothing: gateway never started

# 2. Run gateway directly to see schema errors
openclaw gateway run      # schema errors print immediately

# 3. Validate config
openclaw doctor           # shows validation errors
# openclaw doctor --fix   # fixes permissions but NOT missing models[] arrays (manual edit required)

# 4. Once openclaw.json is valid, port opens within ~4s
```

---

## `~/.local/bin` Precedence Pattern

macOS PATH order: `~/.local/bin` (pos 4) → `/usr/local/bin` (pos 9).

Installing binaries to `~/.local/bin` shadows system paths without `sudo`. This is the correct macOS pattern for any npm/pip tool that tries to write to root-owned paths.

---

## `orama-system/setup_macos.py`

Called from `start.sh` on every boot via:
```bash
python "$SCRIPT_DIR/setup_macos.py" --quiet 2>&1 | sed 's/^/  /' || true
```

What it does (all idempotent):
1. Creates `~/.local/bin`, adds it to PATH in `~/.zshrc` if missing
2. Validates `~/.openclaw/openclaw.json` — adds `models[]` arrays if missing; queries live Ollama for real names
3. Applies 6 alphaclaw.js patches — each has a `detect` string (already-patched marker); skips if already applied
4. Writes `~/.alphaclaw/.macos_patches.json` marker file

**Idempotency contract**: each patch checks `detect in content` before applying. Warns if npm package version changed (`KNOWN_ALPHACLAW_VERSION = "0.9.3"` constant) but still attempts patches.

---

## Rules

1. **npm packages designed for Docker/root will fail on macOS** — check for `/usr/local/bin/` writes and `/etc/cron.d/` references; redirect to `~/.local/bin/` and user crontab
2. **`openclaw.json` schema validation is strict** — gateway exits immediately on failure; check config first before troubleshooting port timeouts
3. **Gateway timeout ≠ gateway crash** — if port never opens, look at config validation first
4. **All pre-flight patches must be idempotent** — `detect` string (patched marker) + `old` string (original marker); apply only when `old` is found
5. **node_modules patches are transient** — `npm install` overwrites alphaclaw.js; `setup_macos.py` re-applies on next boot

---

## Related

- [Session log 2026-04-13](../LESSONS.md#2026-04-13--claude--alphaclaw-macos-compatibility-patches--idempotent-setup-automation)
- [AlphaClaw PR #63 — macOS port](https://github.com/diazMelgarejo/AlphaClaw/tree/pr-4-macos)
- [AlphaClaw docs/wiki/02-macos-bin-path.md](https://github.com/diazMelgarejo/AlphaClaw/blob/feature/MacOS-post-install/docs/wiki/02-macos-bin-path.md)
