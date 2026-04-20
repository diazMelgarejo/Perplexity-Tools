# AlphaClaw Adapter Interface Contract

**Status:** Living document — update after every AlphaClaw upstream merge
**Version:** 0.9.9.8 (aligned with Perpetua-Tools)
**Last verified:** 2026-04-20 against AlphaClaw `feature/MacOS-post-install`

This is the invariant that Perpetua-Tools tests against. When AlphaClaw's surface changes, update this document first, then update PT adapter code.

---

## 1. Prerequisites

AlphaClaw requires:
- Node.js ≥ 22.14.0
- `.env` file with `SETUP_PASSWORD` set
- `npm install` completed
- `npm run build:ui` completed (required for UI assets)

---

## 2. CLI Surface (PT spawns these)

```bash
# Start server on default port (reads PORT from .env, default 3000)
node bin/alphaclaw.js start

# Start on custom port
node bin/alphaclaw.js start --port 3001

# Version string
node bin/alphaclaw.js --version

# Build UI assets (required before first run)
npm run build:ui

# Run full test suite (440 tests)
npm test

# Run watchdog suite only (14 tests, faster)
npm run test:watchdog

# Run with coverage
npm run test:coverage
```

**Environment variable overrides:**
| Variable | Default | Purpose |
|----------|---------|---------|
| `PORT` | `3000` | HTTP server port |
| `SETUP_PASSWORD` | (required) | Auth gate for setup and session login |

**PT sets these via:**
```javascript
const ALPHACLAW_ROOT = process.env.ALPHACLAW_ROOT || '../AlphaClaw';
const env = { ...process.env, PORT: String(port), ALPHACLAW_ROOT };
spawnSync('node', ['bin/alphaclaw.js', 'start'], { cwd: ALPHACLAW_ROOT, env });
```

---

## 3. HTTP API Surface

**Base URL:** `http://127.0.0.1:{PORT}` (default port 3000)

### 3.1 Control Plane — PT adapter uses these

| Method | Path | Auth | Source file | Response shape |
|--------|------|------|-------------|----------------|
| `GET` | `/health` | none | `routes/pages.js:4` | `{status:"ok"}` or `{status:"error"}` |
| `GET` | `/api/status` | setup¹ | `routes/system.js:530` | server state + uptime |
| `GET` | `/api/gateway-status` | setup¹ | `routes/system.js:657` | gateway process health |
| `GET` | `/api/gateway/dashboard` | setup¹ | `routes/system.js:718` | full dashboard data |
| `POST` | `/api/gateway/restart` | setup¹ | `routes/system.js:760` | `{ok:true}` or error |
| `GET` | `/api/restart-status` | setup¹ | `routes/system.js:730` | restart state |
| `POST` | `/api/restart-status/dismiss` | setup¹ | `routes/system.js:744` | dismisses banner |
| `GET` | `/api/onboard/status` | none | `routes/onboarding.js:161` | `{onboarded:bool,...}` |
| `GET` | `/api/alphaclaw/version` | setup¹ | `routes/system.js:604` | version string |
| `GET` | `/api/models` | session² | `routes/models.js:164` | model list |
| `GET` | `/api/models/config` | session² | `routes/models.js:211` | routing config |
| `PUT` | `/api/models/config` | session² | `routes/models.js:234` | update routing config |
| `GET` | `/api/env` | session² | `routes/system.js:369` | env vars (PT must redact) |
| `PUT` | `/api/env` | session² | `routes/system.js:416` | write env vars |

¹ **setup-allowlisted** — accessible during setup phase via `SETUP_API_PREFIXES` in `lib/server/constants.js:380`. Includes `/api/status`, `/api/gateway`, `/api/restart-status`.

² **session auth** — requires active login session (cookie from `/api/auth/login`).

### 3.2 Auth Endpoints — PT needs these to obtain a session

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `POST` | `/api/auth/login` | none | Body: `{password: SETUP_PASSWORD}` → sets session cookie |
| `GET` | `/api/auth/status` | none | `{authenticated: bool}` |
| `POST` | `/api/auth/logout` | none | Invalidates session |

**PT login flow:**
```javascript
// 1. POST /api/auth/login with SETUP_PASSWORD
// 2. Store session cookie from response headers
// 3. Include cookie in all subsequent session² requests
// 4. On 401, re-login and retry once
```

### 3.3 Watchdog — PT observability hooks

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/watchdog/status` | session² | Watchdog health state |
| `GET` | `/api/watchdog/events` | session² | Recent watchdog events |
| `GET` | `/api/watchdog/logs` | session² | Log tail (last N lines) |
| `POST` | `/api/watchdog/repair` | session² | Trigger self-repair |

---

## 4. Config File Schema

### `.env` (AlphaClaw project root)

```
SETUP_PASSWORD=<required>
PORT=3000               # optional, default 3000
```

PT reads this to know the password for auth. Never log or expose `SETUP_PASSWORD`.

### `.openclaw/openclaw.json`

```json
{
  "gateway": {
    "providers": {
      "<provider-name>": {
        "enabled": true,
        "models": ["<model-id>", ...],
        "apiKey": "<redact-in-PT>"
      }
    }
  },
  "channels": { ... },
  "version": "..."
}
```

PT reads this via `GET /api/models/config` (authenticated) or via the MCP tool `alphaclaw_read_config` (which redacts secrets automatically).

**Redaction rule:** PT must strip any key matching `/token|secret|password|key|auth|credential/i` before logging, storing, or passing to orama-system.

### LaunchAgent (macOS only)

```
~/Library/LaunchAgents/com.alphaclaw.hourly-sync.plist
```

PT does not manage LaunchAgents directly. AlphaClaw manages its own LaunchAgent on macOS.

---

## 5. Log Format (OTel target — Gate 3)

AlphaClaw currently logs unstructured stdout. PT's process wrapper will parse and forward as OTel spans.

**Current stdout pattern (examples):**
```
[alphaclaw] git auth shim installed
[alphaclaw] Setup complete -- starting server
[alphaclaw] gateway started on port 3001
[watchdog] gateway health: ok
```

**Target format after PT wrapping:**
```json
{"ts":"2026-04-20T00:00:00Z","level":"info","service":"alphaclaw","component":"gateway","msg":"gateway started","port":3001,"traceId":"...","spanId":"..."}
```

The OTel emitter lives in orama-system: `plugins/alphaclaw_otel_emitter.py`. It reads PT's structured output via OTLP gRPC → otel-collector → Tempo + Prometheus.

---

## 6. How to Enumerate Routes After an Upstream Merge

Run this in the AlphaClaw repo root to re-enumerate all HTTP routes:

```bash
grep -rn "app\.\(get\|post\|put\|delete\|patch\)" lib/server/routes/ \
  | grep -v "node_modules" \
  | sort
```

Then diff against §3 above and update this document. Any change to the control-plane endpoints in §3.1 requires a corresponding update to `packages/alphaclaw-adapter/src/index.js`.

---

## 7. Versioning

This contract tracks AlphaClaw version. Breaking changes require a semver bump in PT.

| AlphaClaw version | Contract version | Breaking changes |
|-------------------|------------------|-----------------|
| `0.9.9` (upstream) | `0.9.9.8` | Initial enumeration |

---

## 8. Reference

- System design: `../../../AlphaClaw/docs/system-design-three-repo-architecture.md` §3
- AlphaClaw routes: `lib/server/routes/` (18 route files)
- Auth allowlist: `lib/server/constants.js:380` (`SETUP_API_PREFIXES`)
- MCP server: `packages/alphaclaw-adapter/src/mcp/server.js`
