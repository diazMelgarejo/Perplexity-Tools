# Plan Review: AlphaClaw Migration Plan 3

## Date: 2026-04-19 | Branch: feature/MacOS-post-install (scaffolding — not committed)

---

## On the MCP question first

> "alphaclaw-mcp — does this make sense under PT logic, or can we make this a function inside existing code?"

Short answer: **keep it as a standalone MCP server, but move it OUT of AlphaClaw into PT.**

### Option A: Standalone MCP server (current, wrong repo — move to PT)

- `claude mcp add --transport stdio alphaclaw -- node lib/mcp/alphaclaw-mcp.js`
- Isolated process: crash doesn't take AlphaClaw down. Xcode/Claude Code can spawn it independently.
- Correct for an external tool. Wrong to live inside AlphaClaw — the plan explicitly says no PT/UTS code in AlphaClaw.

### Option B: WRONG\! Function inside AlphaClaw's Express server

- Mount an `/mcp` HTTP route that speaks JSON-RPC 2.0 over HTTP (not stdio).
- Tightly couples MCP protocol to AlphaClaw internals. If AlphaClaw crashes, MCP dies with it. Violates the "control AlphaClaw via stable external interface" principle.

### **Correct answer for PT migration**

Move `lib/mcp/alphaclaw-mcp.js` and `lib/agents/` wholesale into PT. In PT they call AlphaClaw via its HTTP API / CLI, not via internal requires. The stdio MCP server process is then managed by PT, not AlphaClaw. AlphaClaw stays clean.

The code currently in `lib/mcp/alphaclaw-mcp.js` and `lib/agents/` is **correctly architected as a standalone MCP server** — it just lives in the wrong repo right now. Migration to PT is a cut-and-paste plus swap of internal `require` calls for HTTP calls.

---

## CRITICISM — What's weak or wrong in the plan

### 1. The 3-day timeline is a fiction

Day 1: scaffold two new repos + design adapter API + type all interfaces + move local agent clients.
Day 2: implement full adapter CLI+HTTP + wire all MCP tools + write unit tests + build UTS orchestration skeleton + first E2E scenario.
Day 3: harden retry/backoff + write remaining E2E + file AlphaClaw cleanup PR + finalize all docs + CI green on both new repos.

This is 3–4 weeks of real engineering compressed into 72 hours. The plan correctly identifies the design principles but then attaches a timeline that ignores the work involved in standing up two greenfield repos from scratch (package.json, TypeScript config, CI, test harness, adapter library, MCP toolpack, orchestrator service). **Do not use this timeline. It will demoralize rather than focus.**

### 2. Name confusion is live right now

The plan body says "Perpetua-Tools" and "ὅραμα System" (orama-system). Section B links say `diazMelgarejo/Perplexity-Tools` and `diazMelgarejo/ultrathink-system`. The user's GitHub repos currently have the old names. Until the GitHub rename happens, every reference to PT and UTS in docs, scripts, and `package.json` will be ambiguous. The rename needs to happen (and be recorded) before any scaffolding code references the new names.

- PT = `diazMelgarejo/Perplexity-Tools` renamed → <https://github.com/diazMelgarejo/Perpetua-Tools>
- UTS = `diazMelgarejo/ultrathink-system` renamed → <https://github.com/diazMelgarejo/orama-system>

Update all references to these 2 repos — now **Perpetua** and **orama**\!

### 3. No concrete interface contract is defined

"Stable boundaries" and "typed interfaces" are stated as goals, but the plan doesn't actually define them. What HTTP endpoints does AlphaClaw expose today? What are the exact CLI flags PT will call (e.g. `node bin/alphaclaw.js start --port 3000`)? Without a written API contract (even a one-page OpenAPI stub), the "adapter" is just guesswork that will break every time AlphaClaw upstream merges something. We will work on this and update that living document as we move around the elements between the repos.

### 4. Three reference repos pulling in three incompatible paradigms simultaneously

1. `agentic-stack` → portable `.agent/` folder across IDEs as our **default baseline**, align all code to converge on these conventions
2. `Claude-Desktop-LLM` → `.mcpb` process-per-model pattern
3. `wcgw` → recursive stateful code editing via MCP

Each represents a different architectural bet. Pulling all three into PT at once creates a design surface that is too wide to execute cleanly in a bounded timeline. None of them are dependencies yet — they are "inspiration." Pick one paradigm first, validate it works with AlphaClaw as the backend, then evaluate whether the others compose cleanly.

### 5. "Public NPM starting with 1.0 RC, but not now" defers a decision that affects everything

Package naming, export shape, semver strategy, and scoping all flow from whether PT/UTS are intended to be published. If they are, the internal module structure needs to be designed for it from day one (no barrel exports of internal-only modules, proper `exports` field in package.json, etc.). Deferring this decision means potential painful restructuring later. This restructuring will also pivot to a "release early, release often" strategy that starts with a single RC release (0.9.9.6) and then a series of minor versions leading up to 1.0 Release.

### 6. Observability is hand-wavy

"A minimal metrics endpoint and structured internal logs" is mentioned under a bullet but not designed. Does this mean Prometheus `/metrics`? OpenTelemetry traces? stdout JSON Lines? The UTS orchestrator is supposed to consume AlphaClaw's log stream — if the format isn't defined before the adapter is written, the adapter will be rewritten when the format is decided.

This is the mockup design (placeholder) of what we will build:

```
alphaclaw-observability/
│
├── README.md
├── plugins/
│   └── alphaclaw_otel_emitter.py
│
├── observability/
│   ├── semantic-conventions.yaml
│   ├── metrics.yaml
│   └── bias_detector.py
│
├── config/
│   └── openclaw.json
│
├── .env.example
├── tempo-config.yaml
├── otel-collector.yaml
├── docker-compose.yaml
└── grafana-dashboard.json
```

Zip file attached: `docs/alphaclaw-observability.zip`

### 7. The MCP code we just built violates the plan's own invariant

`lib/mcp/alphaclaw-mcp.js`, `lib/agents/local-agent-client.js`, and `lib/agents/orchestrator.js` are sitting inside AlphaClaw right now. The plan explicitly says "No PT/UTS-specific orchestration code lives in AlphaClaw." We need to either delete these files from AlphaClaw before the pr-4-macos cherry-pick, or explicitly flag them as temporary scaffolding that gets migrated on Day 1 of the PT work. They must not land in pr-4-macos — we will move all of this to the PT backbone.

---

## STEELMAN — Why this plan is actually sound

### 1. The strangler-fig approach is exactly right for this situation

AlphaClaw is a live fork of an active upstream. If PT/UTS import AlphaClaw internals (via `require`), every upstream merge becomes a potential breaking change. Driving AlphaClaw exclusively through its CLI and HTTP surface means PT/UTS are insulated from upstream internals. The adapter absorbs the churn; the orchestrator stays stable. This is the correct pattern.

### 2. Keeping AlphaClaw minimal IS the strategic moat

If the macOS port stays clean and upstreamable, chrysb may merge it. That means `diazMelgarejo` gets upstream recognition, the fork stays small and easy to maintain, and AlphaClaw can track upstream with low friction. Every PT/UTS feature that doesn't land in AlphaClaw is a liability in the fork — the plan correctly sees this.

### 3. The three-repo topology maps cleanly to real system layers

`AlphaClaw` (infrastructure / managed dependency) → `Perpetua-Tools` (middleware / adapters / tooling) → `orama-system` (application / orchestration / meta-intelligence). This is a classic layered architecture and it's correct. The alternative — keeping everything in one repo — produces an unmaintainable monolith that can't track upstream at all.

### 4. "First principles + design doc before code" is the right call given the complexity

The plan explicitly says: draft adapter API and types first, get a design doc reviewed, then implement. Given that PT and orama don't exist yet, this prevents building on unstable foundations. It will save 3x the time in avoided rewrites compared to just starting to code.

### 5. The rename is necessary and should happen now

"Perplexity" is the name of a well-funded AI company with active branding in the exact same market space. Using it in a public npm package (`@perplexity-tools/...`) is a trademark risk that grows with visibility. "Perpetua-Tools" and "ὅραμα System" (orama-system) are ownable, clear, and distinctive. Do the rename before any public package publication — the plan is right to flag this.

### 6. The local-agent-client.js architecture is correct even if the location is wrong

The client we built (Ollama → GLM-5.1:cloud fallback → qwen3.5-local:latest, LM Studio OpenAI-compat) is the right abstraction: a unified `LocalAgentClient` that dispatches to available backends. Migrating it to PT is a cut-and-paste — the design doesn't change, only where it lives. The plan correctly identifies PT as the owner of this code.

### 7. The portable `.agent/` folder from agentic-stack is a genuine unlock

If memory, skills, and protocols can travel with the developer across Claude Code, Cursor, Windsurf, OpenClaw, and OpenCode, that is a productivity multiplier that compounds over time. Identifying it as a design goal — even without a timeline for it — means the PT folder structure can be designed to accommodate it from the start instead of retrofitting it later. Abstract and copy this capability from the repo and apply it as the backbone of a new refactored PT.

### 8. Testing-first + reversible migration prevents the classic rewrite disaster

Tag before removals. Strangler-fig. Green tests before cutover. These three constraints together are the difference between a successful extraction and a six-week refactor that ships nothing. The plan has all three explicitly. That discipline is rare and worth preserving.

---

## Recommended modifications to the plan

1. **Do the GitHub rename first** (Perplexity-Tools → Perpetua-Tools, ultrathink-system → orama-system) before any scaffolding references the new names.

2. **Replace the 3-day timeline with milestone gates:**
   - Gate 0: Repos exist, CI scaffolded, adapter contract written (one-page interface doc)
   - Gate 1: AlphaClaw HTTP adapter works — PT can start/stop/query AlphaClaw
   - Gate 2: MCP toolpack in PT passes integration tests against live AlphaClaw
   - Gate 3: First orama-system orchestration flow runs end-to-end

3. **Move `lib/mcp/` and `lib/agents/` from AlphaClaw** feature branch first to PT and orama-system. Cherry-picking to pr-4-macos is a separate process out of our scope. Flag as PT-destined scaffolding in the commit message, only **AFTER** the move.

4. **Write the adapter interface contract first** — even one page with: CLI flags, HTTP endpoints, config file schema, log format. This becomes the invariant PT tests against.

5. **Pick one external reference repo** (agentic-stack for the `.agent/` portable folder concept) and evaluate the other two after the adapter is working.

6. **Defer public NPM publish decision** but document the intended package names now: `@diazmelgarejo/perpetua-tools`, `@diazmelgarejo/orama-system`. Reserve the npm scopes. All three packages target version **0.9.9.8** after the move and refactoring.
