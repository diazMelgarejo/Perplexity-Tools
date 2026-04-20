import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  ErrorCode,
  McpError,
} from "@modelcontextprotocol/sdk/types.js";
// @ts-ignore
import adapter from "@diazmelgarejo/alphaclaw-adapter";
import orchestrator from "../../local-agents/src/orchestrator.js";

/**
 * ὅραμα-system (orama-system) / Perpetua-Tools 
 * AlphaClaw MCP Server (Gate 2 Scaffold)
 * 
 * Uses the official Model Context Protocol SDK to expose AlphaClaw 
 * administrative commands to Claude Code and the orchestrator.
 */

const server = new Server(
  {
    name: "alphaclaw-mcp",
    version: "0.1.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// ─── Setup Tool List ──────────────────────────────────────────────────────────

server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: "alphaclaw_health",
        description: "Ping the AlphaClaw gateway health endpoint to check liveness. (No-Auth)",
        inputSchema: { type: "object", properties: {}, required: [] },
      },
      {
        name: "alphaclaw_login",
        description: "Login to the AlphaClaw gateway using SETUP_PASSWORD to establish an active session.",
        inputSchema: {
          type: "object",
          properties: {
            password: { type: "string", description: "AlphaClaw Setup Password" },
          },
          required: ["password"],
        },
      },
      {
        name: "alphaclaw_status",
        description: "Fetch detailed metrics and stats about the AlphaClaw instance. (Requires Auth)",
        inputSchema: { type: "object", properties: {}, required: [] },
      },
      {
        name: "alphaclaw_watchdog_logs",
        description: "Pull recent watchdog observability logs from AlphaClaw. (Requires Auth)",
        inputSchema: {
          type: "object",
          properties: {
            lines: { type: "number", description: "Number of rows of recent logs." }
          },
          required: [],
        },
      },
      {
        name: "local_agent_health",
        description: "Check health of Ollama and LM Studio. (Old way via PT local-agents)",
        inputSchema: { type: "object", properties: {}, required: [] },
      },
      {
        name: "local_agent_ask_about_code",
        description: "Delegate a code question to local agent. (Old way)",
        inputSchema: {
          type: "object",
          properties: {
            filePath: { type: "string" },
            question: { type: "string" },
            backend: { type: "string", enum: ["ollama", "lmstudio"] }
          },
          required: ["filePath", "question"]
        }
      }
    ],
  };
});

// ─── Tool Invocation Dispatcher ──────────────────────────────────────────────

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  try {
    switch (request.params.name) {
      case "alphaclaw_health": {
        const result = await adapter.health();
        return {
          content: [
            { type: "text", text: JSON.stringify(result, null, 2) },
          ],
        };
      }

      case "alphaclaw_login": {
        const password = String(request.params.arguments?.password);
        if (!password) {
          throw new McpError(ErrorCode.InvalidParams, "Password required.");
        }
        const result = await adapter.login(password);
        return {
          content: [
            { type: "text", text: JSON.stringify(result, null, 2) },
          ],
        };
      }

      case "alphaclaw_status": {
        const result = await adapter.status();
        return {
          content: [
            { type: "text", text: JSON.stringify(result, null, 2) },
          ],
        };
      }

      case "alphaclaw_watchdog_logs": {
        const lines = request.params.arguments?.lines ? Number(request.params.arguments.lines) : 50;
        const result = await adapter.watchdogLogs(lines);
        return {
          content: [
            { type: "text", text: JSON.stringify(result, null, 2) },
          ],
        };
      }

      case "local_agent_health": {
        const result = await orchestrator.checkAgentHealth();
        return {
          content: [
            { type: "text", text: JSON.stringify(result, null, 2) },
          ],
        };
      }

      case "local_agent_ask_about_code": {
        const filePath = String(request.params.arguments?.filePath);
        const question = String(request.params.arguments?.question);
        const backend = request.params.arguments?.backend ? String(request.params.arguments.backend) : undefined;
        const result = await orchestrator.delegateCodeQuestion({ filePath, question, backend });
        return {
          content: [
            { type: "text", text: JSON.stringify(result, null, 2) },
          ],
        };
      }

      default:
        throw new McpError(ErrorCode.MethodNotFound, `Unknown tool: ${request.params.name}`);
    }
  } catch (err: any) {
    return {
      content: [
        { type: "text", text: `Error calling tool: ${err.message}` },
      ],
      isError: true,
    };
  }
});

// ─── Startup ─────────────────────────────────────────────────────────────────

async function run() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("🚀 AlphaClaw MCP Server started on stdio");
}

run().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
