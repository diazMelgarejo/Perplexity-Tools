#!/usr/bin/env node
/**
 * Stdio MCP server — single-backend local agent (Ollama or LM Studio).
 * Claude Code / dev stdio MCP (not Claude Desktop — Desktop uses vendor/Claude-Desktop-LLM MCPB).
 *
 * Usage:
 *   node packages/local-agents/src/mcp-stdio.mjs --backend ollama
 *   node packages/local-agents/src/mcp-stdio.mjs --backend lmstudio
 */

import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const require = createRequire(import.meta.url);
const __dirname = path.dirname(fileURLToPath(import.meta.url));

const {
  checkAgentHealth,
  listLocalModels,
  delegateCodeQuestion,
  delegateCodeEdit,
} = require("./orchestrator.js");

function parseBackend(argv) {
  const idx = argv.indexOf("--backend");
  if (idx === -1 || !argv[idx + 1]) {
    throw new Error("Missing --backend ollama|lmstudio");
  }
  const backend = argv[idx + 1];
  if (backend !== "ollama" && backend !== "lmstudio") {
    throw new Error(`Invalid backend: ${backend}`);
  }
  return backend;
}

const BACKEND = parseBackend(process.argv);
const SERVER_NAME = `local-agent-${BACKEND}`;

const TOOLS = [
  {
    name: "local_agent_health",
    description: `Check reachability of the ${BACKEND} local agent backend.`,
    inputSchema: { type: "object", properties: {}, required: [] },
  },
  {
    name: "local_agent_list_models",
    description: `List models available on the ${BACKEND} backend.`,
    inputSchema: { type: "object", properties: {}, required: [] },
  },
  {
    name: "local_agent_ask_about_code",
    description: `Ask ${BACKEND} about a file under approved MCP roots.`,
    inputSchema: {
      type: "object",
      properties: {
        filePath: { type: "string" },
        question: { type: "string" },
      },
      required: ["filePath", "question"],
    },
  },
  {
    name: "local_agent_propose_edit",
    description: `Ask ${BACKEND} to propose a diff for a file (not auto-applied).`,
    inputSchema: {
      type: "object",
      properties: {
        filePath: { type: "string" },
        instruction: { type: "string" },
      },
      required: ["filePath", "instruction"],
    },
  },
];

function toolResult(result) {
  return {
    content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
    structuredContent: result,
  };
}

const server = new Server(
  { name: SERVER_NAME, version: "0.9.9.9" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const args = request.params.arguments || {};
  switch (request.params.name) {
    case "local_agent_health": {
      const health = await checkAgentHealth();
      const pinned = health[BACKEND] || { ok: false, error: "unknown backend" };
      return toolResult({ backend: BACKEND, ...pinned, anyAvailable: Boolean(pinned.ok) });
    }
    case "local_agent_list_models": {
      const models = await listLocalModels();
      return toolResult({
        backend: BACKEND,
        models: models[BACKEND] || [],
        errors: models.errors || {},
      });
    }
    case "local_agent_ask_about_code":
      return toolResult(
        await delegateCodeQuestion({
          filePath: String(args.filePath || ""),
          question: String(args.question || ""),
          backend: BACKEND,
        })
      );
    case "local_agent_propose_edit":
      return toolResult(
        await delegateCodeEdit({
          filePath: String(args.filePath || ""),
          instruction: String(args.instruction || ""),
          backend: BACKEND,
        })
      );
    default:
      throw new Error(`Unknown tool: ${request.params.name}`);
  }
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((err) => {
  console.error(`[${SERVER_NAME}] fatal:`, err);
  process.exit(1);
});
