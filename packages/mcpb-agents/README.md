# mcpb-agents

Process-per-model MCP definitions (Claude Desktop / MCPB-style JSON configs).

## Canonical entry

From this directory, both bundles launch:

```text
../local-agents/src/mcp-stdio.mjs --backend ollama|lmstudio
```

Not `../../local-agents` (that incorrectly resolves outside `packages/`).

## Bundles

| File | Backend |
|------|---------|
| `ollama-agent.mcpb` | Ollama @ `127.0.0.1:11435` (env override via `OLLAMA_BASE_URL`) |
| `lmstudio-agent.mcpb` | LM Studio (`LMSTUDIO_BASE_URL`) |

## Install / test

```bash
cd ../local-agents && npm install && npm test
node ../local-agents/src/mcp-stdio.mjs --backend ollama   # stdio MCP — use with MCP client
```

Implementation plan: [`docs/plans/2026-05-31-gate2-implementation-plan.md`](../../docs/plans/2026-05-31-gate2-implementation-plan.md)

Parent: [`docs/2026-05-31-tri-repo-alignment-completion-plan.md`](../../docs/2026-05-31-tri-repo-alignment-completion-plan.md)

Reference: https://github.com/yayoboy/Claude-Desktop-LLM · https://github.com/anthropics/mcpb
