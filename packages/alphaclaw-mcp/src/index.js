"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const index_js_1 = require("@modelcontextprotocol/sdk/server/index.js");
const stdio_js_1 = require("@modelcontextprotocol/sdk/server/stdio.js");
const types_js_1 = require("@modelcontextprotocol/sdk/types.js");
const alphaclaw_adapter_1 = __importDefault(require("@diazmelgarejo/alphaclaw-adapter"));
/**
 * ὅραμα-system (orama-system) / Perpetua-Tools
 * AlphaClaw MCP Server (Gate 2 Scaffold)
 *
 * Uses the official Model Context Protocol SDK to expose AlphaClaw
 * administrative commands to Claude Code and the orchestrator.
 */
const server = new index_js_1.Server({
    name: "alphaclaw-mcp",
    version: "0.1.0",
}, {
    capabilities: {
        tools: {},
    },
});
// ─── Setup Tool List ──────────────────────────────────────────────────────────
server.setRequestHandler(types_js_1.ListToolsRequestSchema, async () => {
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
        ],
    };
});
// ─── Tool Invocation Dispatcher ──────────────────────────────────────────────
server.setRequestHandler(types_js_1.CallToolRequestSchema, async (request) => {
    try {
        switch (request.params.name) {
            case "alphaclaw_health": {
                const result = await alphaclaw_adapter_1.default.health();
                return {
                    content: [
                        { type: "text", text: JSON.stringify(result, null, 2) },
                    ],
                };
            }
            case "alphaclaw_login": {
                const password = String(request.params.arguments?.password);
                if (!password) {
                    throw new types_js_1.McpError(types_js_1.ErrorCode.InvalidParams, "Password required.");
                }
                const result = await alphaclaw_adapter_1.default.login(password);
                return {
                    content: [
                        { type: "text", text: JSON.stringify(result, null, 2) },
                    ],
                };
            }
            case "alphaclaw_status": {
                const result = await alphaclaw_adapter_1.default.status();
                return {
                    content: [
                        { type: "text", text: JSON.stringify(result, null, 2) },
                    ],
                };
            }
            case "alphaclaw_watchdog_logs": {
                const lines = request.params.arguments?.lines ? Number(request.params.arguments.lines) : 50;
                const result = await alphaclaw_adapter_1.default.watchdogLogs(lines);
                return {
                    content: [
                        { type: "text", text: JSON.stringify(result, null, 2) },
                    ],
                };
            }
            default:
                throw new types_js_1.McpError(types_js_1.ErrorCode.MethodNotFound, `Unknown tool: ${request.params.name}`);
        }
    }
    catch (err) {
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
    const transport = new stdio_js_1.StdioServerTransport();
    await server.connect(transport);
    console.error("🚀 AlphaClaw MCP Server started on stdio");
}
run().catch((error) => {
    console.error("Fatal error:", error);
    process.exit(1);
});
//# sourceMappingURL=index.js.map