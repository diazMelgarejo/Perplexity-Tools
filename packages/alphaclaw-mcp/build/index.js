import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema, ErrorCode, McpError, } from "@modelcontextprotocol/sdk/types.js";
import { spawnSync } from "child_process";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
// @ts-ignore
import adapter from "@diazmelgarejo/alphaclaw-adapter";
// @ts-ignore
import orchestrator from "../../local-agents/src/orchestrator.js";
/**
 * ὅραμα-system (orama-system) / Perpetua-Tools
 * AlphaClaw MCP Server — Gate 2 (v0.9.16.9)
 *
 * All 14 tools are custom additions from diazMelgarejo/AlphaClaw
 * feature/MacOS-post-install (v0.9.16.9). None exist in upstream
 * chrysb/alphaclaw:main (v0.9.16).
 *
 * Register:
 *   claude mcp add --transport stdio alphaclaw \
 *     -- node packages/alphaclaw-mcp/build/index.js
 *
 * Tools (14):
 *   alphaclaw_health             — ping gateway health (no auth)
 *   alphaclaw_login              — establish authenticated session
 *   alphaclaw_status             — running state + port
 *   alphaclaw_read_config        — openclaw.json redacted read
 *   alphaclaw_list_providers     — configured AI providers
 *   alphaclaw_tail_logs          — last N lines of hourly-sync.log
 *   alphaclaw_check_env          — .env / SETUP_PASSWORD presence
 *   alphaclaw_build_ui           — npm run build:ui output
 *   alphaclaw_run_tests          — vitest suite (full|watchdog|coverage)
 *   alphaclaw_watchdog_logs      — watchdog observability log pull
 *   local_agent_health           — Ollama + LM Studio reachability
 *   local_agent_list_models      — all models across local backends
 *   local_agent_ask_about_code   — delegate code question to local agent
 *   local_agent_propose_edit     — propose code patch (Claude reviews, NOT auto-applied)
 *
 * References:
 *   Source JS:  packages/alphaclaw-adapter/src/mcp/server.js (Gate 0 copy, 11 tools)
 *   Upstream:   chrysb/alphaclaw:main — no MCP server exists there
 *   MIGRATION:  docs/MIGRATION.md Gate 2
 */
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
// AlphaClaw project root — PT drives AlphaClaw externally via CLI/HTTP only, NEVER require()
const PROJECT_ROOT = process.env.ALPHACLAW_ROOT ||
    path.resolve(__dirname, "..", "..", "..", "..", "AlphaClaw");
const OPENCLAW_DIR = path.join(PROJECT_ROOT, ".openclaw");
const CONFIG_PATH = path.join(OPENCLAW_DIR, "openclaw.json");
const ENV_PATH = path.join(PROJECT_ROOT, ".env");
// ─── Secret redactor (mirrors server.js) ─────────────────────────────────────
const REDACT_KEYS = /token|secret|password|key|auth|credential/i;
function redact(obj) {
    if (!obj || typeof obj !== "object")
        return obj;
    return Object.fromEntries(Object.entries(obj).map(([k, v]) => [
        k,
        REDACT_KEYS.test(k) ? "[REDACTED]" : typeof v === "object" ? redact(v) : v,
    ]));
}
// ─── File-based tool implementations ─────────────────────────────────────────
function readConfig() {
    if (!fs.existsSync(CONFIG_PATH)) {
        return { configured: false, message: "openclaw.json not found — run setup first." };
    }
    try {
        const raw = JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8"));
        return { configured: true, config: redact(raw) };
    }
    catch (e) {
        return { configured: false, error: e.message };
    }
}
function listProviders() {
    const cfg = readConfig();
    if (!cfg.configured)
        return cfg;
    const providers = cfg.config?.gateway?.providers ||
        cfg.config?.providers ||
        {};
    return {
        providers: Object.entries(providers).map(([name, info]) => ({
            name,
            enabled: info?.enabled !== false,
            models: info?.models || [],
        })),
    };
}
function tailLogs(lines = 50) {
    const cap = Math.min(lines, 200);
    const logPath = path.join(OPENCLAW_DIR, "hourly-sync.log");
    if (!fs.existsSync(logPath)) {
        return { found: false, message: `Log not found at ${logPath}` };
    }
    try {
        const content = fs.readFileSync(logPath, "utf8");
        const tail = content.trim().split("\n").slice(-cap).join("\n");
        return { found: true, lines: cap, log: tail };
    }
    catch (e) {
        return { found: false, error: e.message };
    }
}
function checkEnv() {
    const exists = fs.existsSync(ENV_PATH);
    if (!exists) {
        return {
            env_file: false,
            setup_password: false,
            message: ".env not found — create it with SETUP_PASSWORD=yourpassword",
        };
    }
    const content = fs.readFileSync(ENV_PATH, "utf8");
    const hasPassword = /^SETUP_PASSWORD\s*=\s*.+/m.test(content);
    return {
        env_file: true,
        setup_password: hasPassword,
        message: hasPassword
            ? ".env exists and SETUP_PASSWORD is set ✓"
            : ".env exists but SETUP_PASSWORD is missing or empty",
    };
}
function buildUi() {
    try {
        const result = spawnSync("npm", ["run", "build:ui"], {
            cwd: PROJECT_ROOT,
            encoding: "utf8",
            timeout: 60000,
        });
        return {
            exit_code: result.status,
            success: result.status === 0,
            stdout: (result.stdout || "").slice(-3000),
            stderr: (result.stderr || "").slice(-2000),
        };
    }
    catch (e) {
        return { success: false, error: e.message };
    }
}
function runTests(suite) {
    const SUITES = {
        full: ["run"],
        watchdog: [
            "run",
            "tests/server/watchdog.test.js",
            "tests/server/watchdog-db.test.js",
            "tests/server/routes-watchdog.test.js",
        ],
        coverage: ["run", "--coverage"],
    };
    const args = SUITES[suite];
    if (!args)
        return { error: `Unknown suite: ${suite}` };
    try {
        const result = spawnSync("./node_modules/.bin/vitest", args, {
            cwd: PROJECT_ROOT,
            encoding: "utf8",
            timeout: 120000,
        });
        const output = (result.stdout || "") + (result.stderr || "");
        const summaryMatch = output.match(/Tests?\s+\d+[^\n]*/i);
        return {
            suite,
            exit_code: result.status,
            success: result.status === 0,
            summary: summaryMatch ? summaryMatch[0].trim() : "see output",
            output: output.slice(-4000),
        };
    }
    catch (e) {
        return { suite, success: false, error: e.message };
    }
}
// ─── MCP server ───────────────────────────────────────────────────────────────
const server = new Server({ name: "alphaclaw-mcp", version: "0.9.16.9" }, { capabilities: { tools: {} } });
server.setRequestHandler(ListToolsRequestSchema, async () => ({
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
            description: "Check whether the AlphaClaw server is running and on which port. Returns process info and port.",
            inputSchema: { type: "object", properties: {}, required: [] },
        },
        {
            name: "alphaclaw_read_config",
            description: "Read the current openclaw.json configuration. Secrets (tokens, passwords) are redacted. Returns provider list, channel config, and gateway settings.",
            inputSchema: { type: "object", properties: {}, required: [] },
        },
        {
            name: "alphaclaw_list_providers",
            description: "List all AI model providers configured in openclaw.json with their model arrays and enabled state.",
            inputSchema: { type: "object", properties: {}, required: [] },
        },
        {
            name: "alphaclaw_tail_logs",
            description: "Return the last N lines from the AlphaClaw hourly-sync log or npm start output.",
            inputSchema: {
                type: "object",
                properties: {
                    lines: { type: "number", description: "Number of log lines to return (default 50, max 200)" },
                },
                required: [],
            },
        },
        {
            name: "alphaclaw_check_env",
            description: "Verify .env file exists and SETUP_PASSWORD is set. Returns status without revealing the password value.",
            inputSchema: { type: "object", properties: {}, required: [] },
        },
        {
            name: "alphaclaw_build_ui",
            description: "Run `npm run build:ui` in the AlphaClaw project and return stdout/stderr. Use to verify esbuild ARM64 compatibility.",
            inputSchema: { type: "object", properties: {}, required: [] },
        },
        {
            name: "alphaclaw_run_tests",
            description: "Run AlphaClaw test suite. suite can be 'full' (all tests), 'watchdog' (14 tests), or 'coverage'. Returns pass/fail summary.",
            inputSchema: {
                type: "object",
                properties: {
                    suite: {
                        type: "string",
                        enum: ["full", "watchdog", "coverage"],
                        description: "Which test suite to run",
                    },
                },
                required: ["suite"],
            },
        },
        {
            name: "alphaclaw_watchdog_logs",
            description: "Pull recent watchdog observability logs from AlphaClaw. (Requires Auth)",
            inputSchema: {
                type: "object",
                properties: {
                    lines: { type: "number", description: "Number of rows of recent logs." },
                },
                required: [],
            },
        },
        {
            name: "local_agent_health",
            description: "Check which local AI agents (Ollama at 127.0.0.1:11435, LM Studio at 192.168.254.101:1234) are reachable and which models are loaded. Use before delegating tasks.",
            inputSchema: { type: "object", properties: {}, required: [] },
        },
        {
            name: "local_agent_list_models",
            description: "List all AI models available across Ollama and LM Studio. Returns model names per backend.",
            inputSchema: { type: "object", properties: {}, required: [] },
        },
        {
            name: "local_agent_ask_about_code",
            description: "Delegate a code question to a local AI agent (Ollama/LM Studio). Claude acts as planner/reviewer; the local agent does the reading. Good for: understanding a file, finding a bug location, summarizing logic.",
            inputSchema: {
                type: "object",
                properties: {
                    filePath: {
                        type: "string",
                        description: "Path to the file to analyze (relative to project root or absolute)",
                    },
                    question: {
                        type: "string",
                        description: "What to ask about this file (e.g. 'Where is the SETUP_PASSWORD check?')",
                    },
                    backend: {
                        type: "string",
                        enum: ["ollama", "lmstudio"],
                        description: "Force a specific backend (optional — auto-selects best available)",
                    },
                },
                required: ["filePath", "question"],
            },
        },
        {
            name: "local_agent_propose_edit",
            description: "Ask a local AI agent to propose a code edit as a unified diff. The patch is returned for Claude to review — it is NOT applied automatically. Claude must validate before any changes are written.",
            inputSchema: {
                type: "object",
                properties: {
                    filePath: {
                        type: "string",
                        description: "Path to the file to edit (relative to project root or absolute)",
                    },
                    instruction: {
                        type: "string",
                        description: "What change to make (e.g. 'Add null check before accessing config.gateway.providers')",
                    },
                    backend: {
                        type: "string",
                        enum: ["ollama", "lmstudio"],
                        description: "Force a specific backend (optional)",
                    },
                },
                required: ["filePath", "instruction"],
            },
        },
    ],
}));
server.setRequestHandler(CallToolRequestSchema, async (request) => {
    try {
        switch (request.params.name) {
            case "alphaclaw_health": {
                const result = await adapter.health();
                return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
            }
            case "alphaclaw_login": {
                const password = String(request.params.arguments?.password ?? "");
                if (!password)
                    throw new McpError(ErrorCode.InvalidParams, "Password required.");
                const result = await adapter.login(password);
                return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
            }
            case "alphaclaw_status": {
                const result = await adapter.status();
                return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
            }
            case "alphaclaw_read_config": {
                const result = readConfig();
                return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
            }
            case "alphaclaw_list_providers": {
                const result = listProviders();
                return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
            }
            case "alphaclaw_tail_logs": {
                const lines = request.params.arguments?.lines ? Number(request.params.arguments.lines) : 50;
                const result = tailLogs(lines);
                return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
            }
            case "alphaclaw_check_env": {
                const result = checkEnv();
                return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
            }
            case "alphaclaw_build_ui": {
                const result = buildUi();
                return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
            }
            case "alphaclaw_run_tests": {
                const suite = String(request.params.arguments?.suite ?? "full");
                const result = runTests(suite);
                return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
            }
            case "alphaclaw_watchdog_logs": {
                const lines = request.params.arguments?.lines ? Number(request.params.arguments.lines) : 50;
                const result = await adapter.watchdogLogs(lines);
                return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
            }
            case "local_agent_health": {
                const result = await orchestrator.checkAgentHealth();
                return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
            }
            case "local_agent_list_models": {
                const result = await orchestrator.listLocalModels();
                return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
            }
            case "local_agent_ask_about_code": {
                const filePath = String(request.params.arguments?.filePath ?? "");
                const question = String(request.params.arguments?.question ?? "");
                const backend = request.params.arguments?.backend
                    ? String(request.params.arguments.backend)
                    : undefined;
                const result = await orchestrator.delegateCodeQuestion({ filePath, question, backend });
                return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
            }
            case "local_agent_propose_edit": {
                const filePath = String(request.params.arguments?.filePath ?? "");
                const instruction = String(request.params.arguments?.instruction ?? "");
                const backend = request.params.arguments?.backend
                    ? String(request.params.arguments.backend)
                    : undefined;
                const result = await orchestrator.delegateCodeEdit({ filePath, instruction, backend });
                return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
            }
            default:
                throw new McpError(ErrorCode.MethodNotFound, `Unknown tool: ${request.params.name}`);
        }
    }
    catch (err) {
        return {
            content: [{ type: "text", text: `Error calling tool: ${err.message}` }],
            isError: true,
        };
    }
});
async function run() {
    const transport = new StdioServerTransport();
    await server.connect(transport);
    console.error("AlphaClaw MCP Server v0.9.16.9 started on stdio (14 tools)");
}
run().catch((error) => {
    console.error("Fatal error:", error);
    process.exit(1);
});
