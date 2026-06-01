# Track B+C — Claude-Desktop-LLM submodule + real MCPB

**Status:** Implemented on branch `cursor/claude-desktop-mcpb-submodule-74e2`  
**Parent:** [`2026-05-31-tri-repo-alignment-completion-plan.md`](../2026-05-31-tri-repo-alignment-completion-plan.md)

## Goal

- **B:** Keep PT stack integration (orchestrator, `local-agents`, `alphaclaw-mcp`) without coupling Desktop extensions to AlphaClaw.
- **C:** Replace JSON `.mcpb` knockoffs with upstream **MCPB v0.3 ZIP** bundles from [yayoboy/Claude-Desktop-LLM](https://github.com/yayoboy/Claude-Desktop-LLM).

## What changed

| Area | Change |
|------|--------|
| Submodule | `vendor/Claude-Desktop-LLM` @ `01cadc68d64891293fa92275f918a157ea955f93` |
| Build | `scripts/install-claude-desktop-llm.sh` → `@anthropic-ai/mcpb` + upstream `build-extensions.sh` |
| Default install | `Perpetua-Tools/install.sh` |
| Staging | `packages/mcpb-agents/built/*.mcpb` (gitignored) |
| Removed | `packages/mcpb-agents/*.mcpb` JSON configs |

## Verify

```bash
cd /path/to/Perpetua-Tools
bash install.sh --skip-desktop
file packages/mcpb-agents/built/ollama-agent.mcpb   # Zip archive
npx @anthropic-ai/mcpb info packages/mcpb-agents/built/ollama-agent.mcpb
unzip -l packages/mcpb-agents/built/ollama-agent.mcpb | rg manifest.json
```

On macOS with Claude Desktop: `bash scripts/install-claude-desktop-llm.sh --open`

## Rollback

```bash
git submodule deinit -f vendor/Claude-Desktop-LLM
rm -rf vendor/Claude-Desktop-LLM packages/mcpb-agents/built
```

Restore prior JSON knockoffs only if needed for dev — not for Claude Desktop install.
