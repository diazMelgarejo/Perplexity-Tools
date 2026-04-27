# System Design: Three-Repo Architecture

@diazmelgarejo/alphaclaw · @diazmelgarejo/perpetua-tools · @diazmelgarejo/orama-system

> Version: 0.9.9.8 (all three, post-migration)
> Status: SCAFFOLDING — not committed | Branch: feature/MacOS-post-install
> Merges: Migration Plan 3 + Plan Review + Session decisions (2026-04-19)

---

## 1. Problem Statement

AlphaClaw (`diazMelgarejo/AlphaClaw`) is a macOS ARM64 port of `chrysb/alphaclaw`. The goal is to keep it clean and upstreamable while extracting all orchestration, tooling, and intelligence into two external repos. The system must:

- Allow AlphaClaw to track upstream without PT/orama interference
- Let Claude Code, Xcode 26 mcpbridge, Ollama, and LM Studio agents co-manage AlphaClaw installations
- Provide a portable `.agent/` memory+skills layer that works across Claude Code, Cursor, Windsurf, OpenClaw, and OpenCode
- Ship as three independently published npm packages, all at `0.9.9.8` after migration

---

## 2. Repository Roles (Authoritative)

```
┌─────────────────────────────────────────────────────────────────────┐
│  LAYER 1 — Infrastructure / Managed Dependency                      │
│  @diazmelgarejo/alphaclaw  (github: diazMelgarejo/AlphaClaw)        │
│  macOS ARM64 port of chrysb/alphaclaw. Upstream-aligned thin fork.  │
│  Controls: CLI · HTTP API · LaunchAgent · openclaw.json             │
│  NEVER contains: PT adapters, MCP toolpacks, orchestration code     │
└───────────────────────────┬─────────────────────────────────────────┘
                            │  CLI + HTTP only (no internal imports)
┌───────────────────────────▼─────────────────────────────────────────┐
│  LAYER 2 — Middleware / Adapters / Tooling                          │
│  @diazmelgarejo/perpetua-tools  (github: diazMelgarejo/Perpetua-Tools) │
│  (renamed from Perplexity-Tools — trademark risk eliminated)        │
│  Contains: AlphaClaw adapter · MCP toolpack · local-agent clients   │
│            (Ollama + LM Studio) · Xcode integration scripts         │
│            · .agent/ portable folder skeleton · CI for adapters     │
└───────────────────────────┬─────────────────────────────────────────┘
                            │  PT adapter APIs (typed contracts)
┌───────────────────────────▼─────────────────────────────────────────┐
│  LAYER 3 — Application / Orchestration / Meta-Intelligence          │
│  @diazmelgarejo/orama-system  (github: diazMelgarejo/orama-system)  │
│  (renamed from ultrathink-system — ὅραμα = vision/revelation) │
│  Contains: Orchestrator service · Planning/execution flows          │
│            · Session management · Knowledge routing                 │
│            · E2E tests · OTel observability stack                   │
└─────────────────────────────────────────────────────────────────────┘
```

### What moves OUT of AlphaClaw → Perpetua-Tools

| Current location (AlphaClaw) | Destination (PT) | Notes |
|---|---|---|
| `lib/mcp/alphaclaw-mcp.js` | `packages/alphaclaw-adapter/src/mcp/server.js` | Swap `require` → HTTP calls |
| `lib/agents/local-agent-client.js` | `packages/local-agents/src/client.js` | Cut-and-paste, no logic change |
| `lib/agents/orchestrator.js` | `packages/local-agents/src/orchestrator.js` | Cut-and-paste, no logic change |
| `scripts/fix-xcode-claude.sh` | `scripts/fix-xcode-claude.sh` | PT owns Xcode integration |
| `docs/xcode-claude-integration.md` | `docs/xcode-claude-integration.md` | PT owns Xcode docs |
| `tests/server/local-agent-client.test.js` | `packages/local-agents/tests/` | Travels with code |

**These files must NOT be cherry-picked into pr-4-macos.** They are PT-destined scaffolding committed only to `feature/MacOS-post-install` until the move is complete and proven operational by tests.

---

## 3. Interface Boundaries (Living Contract — update as AlphaClaw evolves)

### 3.1 AlphaClaw CLI surface (PT calls these)

```bash
node bin/alphaclaw.js start                    # start server (reads .env)
node bin/alphaclaw.js start --port 3001        # custom port
node bin/alphaclaw.js stop                     # graceful shutdown (if implemented)
node bin/alphaclaw.js --version                # version string
```

### 3.2 AlphaClaw HTTP API surface (PT polls/drives these)

Verified via `grep` across `lib/server/routes/` on 2026-04-20. Auth column: **none** = unauthenticated, **setup** = accessible during setup via `SETUP_API_PREFIXES` (constants.js:380), **session** = requires active login session.

#### Control plane — PT adapter uses these

| Method | Path | Auth | Source | Purpose |
|---|---|---|---|---|
| GET | `/health` | none | pages.js:4 | Liveness probe — 200 + `{status:"ok"}` |
| GET | `/api/status` | setup | system.js:530 | Server state, uptime, connected providers |
| GET | `/api/gateway-status` | setup | system.js:657 | Gateway process health |
| GET | `/api/gateway/dashboard` | setup | system.js:718 | Full gateway dashboard data |
| POST | `/api/gateway/restart` | setup | system.js:760 | Restart the gateway process |
| GET | `/api/restart-status` | setup | system.js:730 | Restart state (for polling after restart) |
| POST | `/api/restart-status/dismiss` | setup | system.js:744 | Dismiss restart required banner |
| GET | `/api/onboard/status` | none | onboarding.js:161 | Onboarding completion state |
| GET | `/api/alphaclaw/version` | setup | system.js:604 | Installed version string |
| GET | `/api/models` | session | models.js:164 | List available AI models |
| GET | `/api/models/config` | session | models.js:211 | Model routing config |
| PUT | `/api/models/config` | session | models.js:234 | Update model routing config |
| GET | `/api/env` | session | system.js:369 | Read env vars (PT must redact secrets) |
| PUT | `/api/env` | session | system.js:416 | Write env vars |

#### Auth endpoints — PT needs these to obtain session

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/auth/login` | none | Login with SETUP_PASSWORD → session cookie |
| GET | `/api/auth/status` | none | Check if session is active |
| POST | `/api/auth/logout` | none | Invalidate session |

#### Watchdog — PT observability hooks

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/watchdog/status` | session | Watchdog health state |
| GET | `/api/watchdog/events` | session | Recent watchdog events |
| GET | `/api/watchdog/logs` | session | Watchdog log tail |
| POST | `/api/watchdog/repair` | session | Trigger gateway self-repair |

#### Full route inventory (reference — 50+ routes across 18 route files)

`agents.js` · `auth.js` · `browse/index.js` · `codex.js` · `cron.js` · `doctor.js` · `gmail.js` · `google.js` · `models.js` · `nodes.js` · `onboarding.js` · `pages.js` · `pairings.js` · `proxy.js` · `system.js` · `telegram.js` · `usage.js` · `watchdog.js` · `webhooks.js`

PT adapter only needs the **Control plane** and **Auth** groups above. The rest are application-level routes (Telegram, Gmail, Google OAuth, Codex, etc.) that PT does not manage.

> **Living contract:** Run `grep -rn "app\.\(get\|post\|put\|delete\)" lib/server/routes/` to re-enumerate after any AlphaClaw upstream merge. Update this table when the surface changes.

### 3.3 AlphaClaw config files (PT manages these)

```
.env                          SETUP_PASSWORD, PORT, any secrets
.openclaw/openclaw.json       gateway, providers, channel config
~/Library/LaunchAgents/       com.alphaclaw.hourly-sync.plist (darwin only)
```

### 3.4 Log stream format (OTel target — see §6)

AlphaClaw currently logs to stdout in unstructured format. PT adapter wraps the process and parses stdout → OTel spans. Target format after PT wrapping:

```json
{"ts":"2026-04-19T10:00:00Z","level":"info","service":"alphaclaw","msg":"...","traceId":"..."}
```

---

## 4. Perpetua-Tools — Suggested New Backbone Repo Structure

Adapt the existing repo structure to this suggestion, think of migration with minimal changes.

```ascii
perpetua-tools/                          @diazmelgarejo/perpetua-tools@0.9.9.8
│
├── .agent/                              ← agentic-stack portable folder (BASELINE)
│   ├── memory/                          agent memory, context, lessons
│   ├── skills/                          reusable skill definitions
│   └── protocols/                       interaction protocols
│
├── packages/
│   ├── alphaclaw-adapter/               AlphaClaw HTTP+CLI control library
│   │   ├── src/
│   │   │   ├── client.ts                typed HTTP client for AlphaClaw API
│   │   │   ├── cli.ts                   CLI wrapper (spawn + manage process)
│   │   │   ├── config.ts                .env + openclaw.json management
│   │   │   └── mcp/
│   │   │       └── server.js            alphaclaw-mcp (moved from AlphaClaw)
│   │   ├── tests/
│   │   └── package.json
│   │
│   ├── local-agents/                    Ollama + LM Studio clients
│   │   ├── src/
│   │   │   ├── client.js                LocalAgentClient (moved from AlphaClaw)
│   │   │   └── orchestrator.js          delegateCodeQuestion/Edit (moved)
│   │   ├── tests/
│   │   └── package.json
│   │
│   └── mcpb-agents/                     .mcpb process-per-model (Claude-Desktop-LLM pattern)
│       ├── ollama-agent.mcpb            reasoning + code analysis
│       ├── lmstudio-agent.mcpb          server exposure for sub-agent spawning
│       └── package.json
│
├── scripts/
│   ├── fix-xcode-claude.sh              (moved from AlphaClaw)
│   ├── install-gstack.sh                (moved from AlphaClaw)
│   └── setup-macos-sandbox.sh           (moved from AlphaClaw)
│
├── docs/
│   └── xcode-claude-integration.md      (moved from AlphaClaw)
│
├── CLAUDE.md                            agent context for PT work
├── package.json                         workspace root
└── .github/workflows/ci.yml            adapter + MCP integration tests
```

### agentic-stack `.agent/` as the backbone

The `.agent/` portable folder is the first paradigm we adopt (priority 1 from plan review). Its structure travels with the developer across all supported IDEs. PT's `.agent/` folder will:

- Store AlphaClaw adapter configuration and discovered endpoint contracts
- Hold gstack skills symlinks/references
- Maintain session context between Perpetua-Tools and orama-system runs
- Follow the agentic-stack convention exactly — no invented schema, can we put this as a dependency or just copy?

---

## 5. orama-System —  Suggested New Backbone Repo Structure

Adapt the existing repo structure to this suggestion, think of migration with minimal changes.

```ascii
orama-system/                            @diazmelgarejo/orama-system@0.9.9.8
│
├── .agent/                              ← same agentic-stack portable folder
│
├── src/
│   ├── orchestrator/
│   │   ├── planner.ts                   planning engine (Claude = planner)
│   │   ├── executor.ts                  task dispatch to PT adapters
│   │   ├── session.ts                   session lifecycle management
│   │   └── router.ts                    knowledge + agent routing
│   │
│   ├── flows/                           named workflow definitions
│   │   ├── code-review.ts               read → analyze → propose → review
│   │   ├── build-verify.ts              build:ui → test → watchdog → report
│   │   └── xcode-sync.ts                mcpbridge status → MCP tools → verify
│   │
│   └── observability/                   OTel stack (see §6)
│       ├── emitter.ts                   wraps AlphaClaw stdout → OTel spans
│       └── metrics.ts                   Prometheus-compatible /metrics endpoint
│
├── tests/
│   ├── e2e/                             full-stack E2E scenarios
│   └── integration/                     PT adapter contract tests
│
├── docker-compose.yaml                  OTel collector + Tempo + Grafana
└── package.json
```

---

## 6. Observability Stack (orama-system owns this? Plan more)

Design decision: **OpenTelemetry → Prometheus** scrape. Rationale: trace-first gives causality; metrics follow from spans. AlphaClaw stdout is structured by the PT adapter's process wrapper before OTel emission. We are committed to OTel, but not to what consumes on top of it, the zip was only a sample?

```
AlphaClaw process (stdout)
        │
        ▼
PT adapter / process wrapper
  alphaclaw_otel_emitter.py (or .ts)
        │  OTLP gRPC
        ▼
otel-collector.yaml
        │
   ┌────┴────┐
   ▼         ▼
Tempo     Prometheus
(traces)  (metrics)
   └────┬────┘
        ▼
```

File targets (live in orama-system, not AlphaClaw):

```
orama-system/
├── plugins/alphaclaw_otel_emitter.py    process wrapper → OTel spans
├── observability/
│   ├── semantic-conventions.yaml        span names, attribute keys
│   ├── metrics.yaml                     counter/histogram definitions
│   └── bias_detector.py                 log anomaly detection
├── config/openclaw.json                 reference config for adapter tests
├── .env.example
├── tempo-config.yaml
├── otel-collector.yaml
└── grafana-dashboard.json
```

---

## 7. Version Strategy

All three packages move to `0.9.9.8` simultaneously after the migration is complete and verified. Before that point:

| Package | Current | After move |
|---|---|---|
| `@diazmelgarejo/alphaclaw` | `0.9.9` (pr-4-macos follows upstream) | `0.9.9.8` on feature branch |
| `@diazmelgarejo/perpetua-tools` | does not exist yet | `0.9.9.8` (RC) |
| `@diazmelgarejo/orama-system` | does not exist yet | `0.9.9.8` (RC) |

Release strategy: "release early, release often" — `0.9.9.8` is the first public RC. Minor patch bumps (`0.9.9.9`, `0.9.9.10`...) as features land. `1.0.0` when E2E suite is green and the adapter contract is stable.

npm scopes to reserve now:

- `@diazmelgarejo/alphaclaw` ← already owned
- `@diazmelgarejo/perpetua-tools` ← reserve before scaffold
- `@diazmelgarejo/orama-system` ← reserve before scaffold

---

## 8. Migration — Milestone Gates (replaces the 3-day fiction)

### Gate 0 — Foundations (prerequisite for all other gates)

- [ ] GitHub repos renamed: `Perpetua-Tools`, `orama-system`
- [ ] npm scopes reserved: `@diazmelgarejo/perpetua-tools`, `@diazmelgarejo/orama-system`
- [ ] AlphaClaw HTTP endpoints enumerated and documented in §3.2 above
- [ ] agentic-stack `.agent/` folder convention adopted — PT root uses this layout
- [ ] gstack installed on Mac (`bash scripts/install-gstack.sh`, requires bun)
- [ ] Both new repos: `package.json`, TypeScript config, CI scaffold, lint, empty test harness
- [ ] `lib/mcp/` and `lib/agents/` tagged for removal in AlphaClaw feature branch

### Gate 1 — AlphaClaw Adapter Working

- [ ] `packages/alphaclaw-adapter` in PT: typed HTTP client + CLI wrapper
- [ ] PT can: start AlphaClaw, check health, read config, tail logs — all via HTTP/CLI
- [ ] `alphaclaw-mcp.js` moved to PT; internal `require` calls replaced with HTTP
- [ ] Adapter integration tests pass against live AlphaClaw on Mac
- [ ] `lib/mcp/` and `lib/agents/` removed from AlphaClaw feature branch

### Gate 2 — MCP Toolpack + Local Agents in PT

- [ ] `packages/local-agents` in PT: `LocalAgentClient` + orchestrator moved from AlphaClaw
- [ ] `packages/mcpb-agents` scaffolded: `ollama-agent.mcpb`, `lmstudio-agent.mcpb`
- [ ] MCP toolpack registered: `claude mcp add --transport stdio perpetua -- node packages/alphaclaw-adapter/src/mcp/server.js`
- [ ] All 11 MCP tools pass smoke test against live AlphaClaw
- [ ] Xcode integration scripts moved to PT, `fix-xcode-claude.sh` updated to reference new locations

### Gate 3 — orama-System First Flow

- [ ] orama-system repo scaffolded with orchestrator, planner, executor stubs
- [ ] First E2E workflow: `build-verify.ts` — triggers `npm run build:ui` via PT adapter, asserts exit 0
- [ ] OTel emitter wraps AlphaClaw stdout → Tempo traces visible in Grafana
- [ ] All AlphaClaw tests still green (no regression)

### Gate 4 — RC Release

- [ ] All three packages at `0.9.9.8`
- [ ] `npm pack --dry-run` passes for all three
- [ ] E2E suite green: code-review flow, build-verify flow, xcode-sync flow
- [ ] `npm publish --access public` for all three

---

## 9. Local Agent Orchestration (cross-repo)

The planning pattern — Claude as orchestrator, local agents as workers — spans PT and orama:

```
orama-system/orchestrator (planner)
        │
        │  delegates subtasks
        ▼
perpetua-tools/local-agents/orchestrator.js
        │
        │  dispatches to best available backend
        ├──► Ollama  127.0.0.1:11435
        │    primary: GLM-5.1:cloud
        │    fallback: qwen3.5-local:latest
        │
        └──► LM Studio  192.168.254.101:1234
             model: whatever is loaded
```

Contract: local agents read files and propose patches (unified diff). Claude reviews and applies. No patch is applied without Claude review. This invariant is enforced at the orchestrator level — the `proposeCodeEdit` function returns a diff; the apply step requires explicit approval.

---

## 10. gstack Integration

gstack v1.3 provides the `/browse`, `/review`, `/ship`, `/qa`, `/investigate` and planning skills used across all three repos. Rules:

- ALWAYS use `/browse` for web browsing — never `mcp__Claude_in_Chrome__*` directly
- Use `/plan-eng-review` before any Gate 0→1 transition
- Use `/ship` pre-release checklist before any `npm publish`
- Use `/investigate` for root-cause analysis of adapter failures

Install: `bash scripts/install-gstack.sh` (requires bun). See `CLAUDE.md §gstack` for full skill table. Harmonize and merge with all existing markdowns, lessons, and skills?

---

## 11. Trade-off Analysis

| Decision | Trade-off accepted |
|---|---|
| Strangler-fig via HTTP only, no internal imports | Slightly more latency per AlphaClaw query; gains: zero coupling to upstream internals |
| agentic-stack `.agent/` as baseline (not invented schema) | Convention lock-in to one repo; gains: immediate IDE portability, battle-tested |
| OTel+Tempo over Prometheus-only | More infra to run locally; gains: trace causality, not just metrics |
| All three packages at `0.9.9.8` simultaneously | Coordinated release complexity; gains: consistent version story for users |
| Milestone gates over sprint days | Slower perceived start; gains: no demoralizing missed deadlines, quality gates enforced |
| wcgw recursive editing deferred | One less paradigm to integrate now; gains: focus on adapter stability first |

---

## 12. Invariants — Never Break

| Rule | Enforced by |
|---|---|
| AlphaClaw read-only onboarding guard intact | `lib/server/onboarding/index.js` — do not touch |
| `sanitizeOpenclawConfig()` runs before every gateway spawn | `bin/alphaclaw.js` — upstream invariant |
| No writes to `/usr/local/bin` or `/etc/cron.d` on darwin | `lib/platform.js` → `~/.local/bin`, `~/Library/LaunchAgents` |
| `lib/mcp/` and `lib/agents/` never land in `pr-4-macos` | Enforced by branch rules — feature branch only until moved to PT and confirmed operational by new tests |
| No patch applied by local agent without Claude review | `proposeCodeEdit()` returns diff only — apply is explicit |
| PT drives AlphaClaw via CLI/HTTP only — never `require()` | Adapter interface contract §3 |
| All AlphaClaw tests green before any Gate transition | CI must pass |

---

## Next Actions (in order — do not skip)

1. **Rename GitHub repos** → Perpetua-Tools, orama-system (do this manually on GitHub) DONE
2. **Reserve npm scopes** → `npm login && npm org:create diazmelgarejo` if not done
3. **Enumerate AlphaClaw HTTP endpoints** → `grep -r "router\." lib/server/` and fill in §3.2
4. **Scaffold PT repo** → `package.json`, TypeScript, CI, empty `packages/alphaclaw-adapter/`
5. **Move AlphaClaw MCP+agents code to PT** → after PT scaffold exists, before pr-4-macos cherry-pick
6. **Install gstack on Mac** → `bash scripts/install-gstack.sh` (needs bun first)

---

## Final Links and instructions

Read all files first. Ask me questions using AskUserQuestion before you execute. Do not guess. I will clarify.

A. The Repo Links that will serve as example and inspiration, or we can git submodule dependency:

1. <https://github.com/yayoboy/Claude-Desktop-LLM> Take a cue from handling ollama and LM-Studio models with two files:
 •  ollama-agent.mcpb reasoning and reading code for analysis
 •  lmstudio-agent.mcpb could expose the server for Claude to spawn sub-agents, this repo can be a dependency?
2. <https://github.com/rusiaaman/wcgw> MCP could do the actual code editing recursively called by any agent ([The maintainer’s own warning matters: for clients that already have shell/filesystem tools, wcgw may create duplicate tool choices and token waste. It shines more in clients that lack strong local shell and file access.](https://github.com/rusiaaman/wcgw/discussions/58))
3. <https://github.com/codejunkie99/agentic-stack> get only the pluggability here, do not ingest, converge with its logic for Portable ".agent/" folder (memory + skills + protocols) that plugs into Claude Code, Cursor, Windsurf, OpenCode, OpenClaw, Hermes, or DIY Python and keeps accumulated knowledge, we need this

B. The Repo Links we are working on (where it will land):

i. <https://github.com/diazMelgarejo/AlphaClaw> the branch "feature/MacOS-post-install" will be our home to prepare the thin custom add-ons and configuration on top of it for PT & UTS use (dependency)

ii. old PT = `diazMelgarejo/Perplexity-Tools` renamed → <https://github.com/diazMelgarejo/Perpetua-Tools> main

iii. old UTS = `diazMelgarejo/ultrathink-system` renamed → <https://github.com/diazMelgarejo/orama-system> main
