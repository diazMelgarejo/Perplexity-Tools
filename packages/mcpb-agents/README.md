# mcpb-agents — Claude Desktop extensions (upstream MCPB)

Real **MCP Bundle** (`.mcpb`) artifacts from the first-class git submodule
[`vendor/Claude-Desktop-LLM`](../../vendor/Claude-Desktop-LLM) ([yayoboy/Claude-Desktop-LLM](https://github.com/yayoboy/Claude-Desktop-LLM)).

We do **not** ship JSON “knockoff” configs here anymore. Bundles are ZIP archives with
`manifest.json` (MCPB v0.3), built by upstream `scripts/build-extensions.sh` and
`@anthropic-ai/mcpb pack`.

## Build and stage

```bash
# From Perpetua-Tools repo root (default in install.sh):
bash install.sh

# Or only the Desktop LLM step:
bash scripts/install-claude-desktop-llm.sh
```

Output: `packages/mcpb-agents/built/`

| File | Upstream extension |
|------|-------------------|
| `ollama-agent.mcpb` | Ollama tools (`ollama_query`, `ollama_chat`, …) |
| `lmstudio-agent.mcpb` | LM Studio tools (`lmstudio_query`, …) |

## Install in Claude Desktop

1. Build (above).
2. Claude Desktop → **Settings → Extensions → Advanced → Install Extension…**
3. Select each `.mcpb` under `built/`.

On macOS: `bash scripts/install-claude-desktop-llm.sh --open` opens the bundles in Claude Desktop.

Configure **server URL**, **default model**, and **timeout** in the extension UI (`user_config` in manifest) — same as upstream.

## Stack integration (PT glue, not AlphaClaw)

| Surface | Role |
|---------|------|
| **Claude Desktop** | These `.mcpb` bundles (upstream behavior, no AlphaClaw dependency) |
| **Claude Code** | `packages/alphaclaw-mcp` (14 tools, stdio MCP) |
| **PT orchestrator** | `packages/local-agents` for routing/tests; optional env hints in `built/stack-env.example` |

AlphaClaw is not required to build or run these extensions.

## Submodule

```bash
git submodule update --init vendor/Claude-Desktop-LLM
```

Pin updates intentionally: bump submodule commit + rebuild MCPB when upstream releases.

References: [Anthropic MCPB](https://github.com/anthropics/mcpb) · [Claude Desktop extensions](https://www.anthropic.com/engineering/desktop-extensions)
