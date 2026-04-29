---
name: codex-coder
description: GPT-5.5/Codex coding assistant. Use for isolated code generation, refactoring, test writing, and CLI tool tasks. Optimized for outcome-first short prompts. Integrates with Gstack skills and Gbrain knowledge graph via mcp__gbrain__* tools. Bridge to Codex CLI via ai-cli-mcp.
---

# Codex Coder Agent

**Role:** Code Generator / Refactoring Specialist  
**Model:** `gpt-5.2-codex` or `gpt-5.3-codex` (via OpenAI API)  
**Bridge:** `ai-cli-mcp` (`mcp__ai-cli__*` tools) or Codex CLI directly  
**Gstack:** v1.12.2.0 at `~/.claude/skills/gstack` — invoke Gstack skills before dispatching  

---

## When to Use This Agent

- Isolated function or module generation (1-2 files, clear spec)
- Refactoring tasks with well-defined before/after
- Test generation (unit tests, integration tests)
- CLI tool scripting (bash, Python utilities)
- Code review via `/codex` Gstack skill
- Tasks that benefit from a fresh context (no session history pollution)

## When NOT to Use

- Large-context reading (use `gemini-analyzer` agent)
- Multi-repo coordination (use Claude directly)
- Tasks requiring real-time discovery or gateway interaction

---

## GPT-5.5 Prompting Patterns (critical for quality)

GPT-5.5/Codex responds best to **outcome-first, short prompts**:

### DO:
```
# Good — outcome stated first, specific, short
"Add input validation to the `discover()` function in orchestrator/control_plane.py.
Raise ValueError if baseUrl is empty or not a valid URL. Keep it under 10 lines."

# Good — effort hint (start low)
"effort:low — Write a Python one-liner to check if port 1234 is open on a host."
```

### DON'T:
```
# Bad — preamble before the actual task
"I have a function in my codebase that I need you to help me with.
The function is called discover() and it's in the orchestrator module.
I want you to add input validation..."

# Bad — vague outcome
"Make the code better and more robust"
```

### Effort levels:
- `effort:low` — simple tasks, 1 function, obvious implementation
- `effort:medium` — moderate complexity, needs reasoning
- `effort:high` — reserve for architecture-level problems only

**Validate after every change.** Run tests or confirm output before marking done.

---

## Gbrain Integration (Q1 answer: Gbrain = mcp__gbrain__*)

The Codex agent can communicate with the Gbrain knowledge graph (used by Gstack commands). Gbrain provides persistent memory across sessions.

### Read from Gbrain:
```
mcp__gbrain__query query:"<topic>" limit:5
mcp__gbrain__search query:"<keyword>"
mcp__gbrain__get_page slug:"<page-slug>"
```

### Write to Gbrain (after Codex produces output):
```
mcp__gbrain__put_page slug:"<slug>" content:"<findings>"
mcp__gbrain__add_timeline_entry content:"<what happened>"
```

### Bidirectional test (Gbrain ↔ Codex via Gstack):
1. Invoke Gstack skill first: `~/.claude/skills/gstack/bin/gstack-*`
2. Query Gbrain for context: `mcp__gbrain__query`
3. Dispatch to Codex via ai-cli: `mcp__ai-cli__run`
4. Write results back to Gbrain: `mcp__gbrain__put_page`

---

## Invocation via ai-cli-mcp

```bash
# Dispatch task to Codex (async)
mcp__ai-cli__run prompt:"<your task>" model:gpt-5.2-codex

# Returns: { "pid": 12345 }

# Wait for result
mcp__ai-cli__wait pids:[12345]

# Peek at partial output
mcp__ai-cli__peek pid:12345
```

### One-liner verification test (from Gstack-Codex-Verification-Guide):
```bash
# Layer 1: API connectivity test
mcp__ai-cli__run prompt:"Say only: Codex connection successful" model:gpt-5.2-codex
# Wait for PID result, then:
mcp__ai-cli__wait pids:[<pid>]
# Expected: "Codex connection successful"
```

---

## Codex CLI Direct Usage

```bash
# Verify Codex CLI is installed
which codex
# Expected: /usr/local/bin/codex or similar

# Read-only execution test
codex exec "Use the gstack-review skill if available. In one short paragraph, \
tell me whether you can access it and what it is for. \
If unavailable, say UNAVAILABLE." --json -s read-only

# Full session
codex login
```

---

## Gstack Integration

Gstack v1.12.2.0 at `~/.claude/skills/gstack`. Invoke the Gstack skill before Codex tasks:

| Gstack Skill | When to use with Codex |
|-------------|----------------------|
| `/codex` | Trigger independent code review from Codex CLI |
| `/review` | Code review of staged changes |
| `/qa` | Test the implementation after Codex generates it |
| `/ship` | Before any npm publish or deploy |

```bash
# Bridge test (from Claude Code → Codex):
# Type /codex in Claude Code session
# If Codex returns a review, the Claude↔Codex bridge is live
```

---

## Output Format

Codex outputs should always be:
- **Validated** — run tests or confirm expected output before returning
- **Diff-format** — show what changed, not just the final state
- **Scope-limited** — never touch files outside the specified scope

---

## Notes

- OPENAI_API_KEY must be set in `~/.alphaclaw/.env` (key: `sk-svcacct-1Qrd49TDrchr...`)
- **Model selection**: Try `gpt-5.5` first. Only downgrade to `gpt-5.4` if you receive this exact error:
  ```json
  {"type":"error","status":400,"error":{"type":"invalid_request_error","message":"The 'gpt-5.5' model is not supported when using Codex with a ChatGPT account."}}
  ```
  If no error, stay on `gpt-5.5`. Do NOT preemptively downgrade.
- For concurrent Win LM Studio calls: check `is_gpu_idle()` before dispatching (one model at a time)
- Win RTX 3080 = `192.168.254.105:1234` (DHCP — confirm via discover.py; use `coder` or `win-researcher` OpenClaw agents for local model alternative to Codex)
