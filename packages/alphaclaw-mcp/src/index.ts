import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  ErrorCode,
  McpError,
} from "@modelcontextprotocol/sdk/types.js";
import { spawnSync } from "child_process";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
// @ts-ignore
import adapter from "@diazmelgarejo/alphaclaw-adapter";
// @ts-ignore
import orchestrator from "../../local-agents/src/orchestrator.js";
import {
  isToolAllowed,
  profileStartupSummary,
  toolDisabledMessage,
} from "./mcp-profiles.js";

/**
 * ὅραμα-system (orama-system) / Perpetua-Tools
 * AlphaClaw MCP Server — canonical adapter + controller primitive (v0.9.16.9)
 *
 * This is the SINGLE authoritative MCP entry point for ALL AlphaClaw functions.
 * It absorbs and supersedes:
 *   - Gate 0: packages/alphaclaw-adapter/src/mcp/server.js  (11-tool JS copy, now deleted)
 *   - Gate 2: previous 6-tool TS scaffold                   (expanded to 14 tools)
 *
 * All 14 tools are custom additions from diazMelgarejo/AlphaClaw
 * feature/MacOS-post-install (v0.9.16.9). None exist in upstream
 * chrysb/alphaclaw:main (v0.9.16). This package drives AlphaClaw via its
 * CLI/HTTP surface only — NEVER require()s AlphaClaw internals.
 *
 * Register (Claude Code):
 *   claude mcp add --transport stdio alphaclaw \
 *     -- node packages/alphaclaw-mcp/build/index.js
 *
 * Env:
 *   ALPHACLAW_ROOT  — path to AlphaClaw project dir (default: ../AlphaClaw sibling)
 *   ALPHACLAW_MCP_PROFILE — readonly (default) | elevated
 *   ALPHACLAW_MCP_ENABLE_PROCESS_TOOLS — opt-in build_ui/run_tests when profile=readonly
 *   ALPHACLAW_MCP_ENABLE_MUTATING_TOOLS — opt-in login/propose_edit when profile=readonly
 *
 * Tools (14):
 *
 *   HTTP/adapter tools (require running AlphaClaw gateway):
 *   alphaclaw_health             — ping gateway health endpoint (no auth)
 *   alphaclaw_login              — establish authenticated session via SETUP_PASSWORD
 *   alphaclaw_status             — gateway running state + port (HTTP)
 *   alphaclaw_watchdog_logs      — watchdog observability log pull (authenticated)
 *
 *   File-based tools (work without running gateway):
 *   alphaclaw_read_config        — openclaw.json read, secrets redacted
 *   alphaclaw_list_providers     — configured AI providers + model arrays
 *   alphaclaw_tail_logs          — last N lines of hourly-sync.log
 *   alphaclaw_check_env          — .env / SETUP_PASSWORD presence check
 *
 *   Process-spawning tools (run in AlphaClaw project):
 *   alphaclaw_build_ui           — npm run build:ui (esbuild ARM64 verification)
 *   alphaclaw_run_tests          — vitest suite: full | watchdog | coverage
 *
 *   Local agent tools (Ollama / LM Studio delegation):
 *   local_agent_health           — Ollama + LM Studio reachability
 *   local_agent_list_models      — all models across local backends
 *   local_agent_ask_about_code   — delegate code question to local agent (Claude reviews)
 *   local_agent_propose_edit     — propose unified-diff patch (NOT auto-applied)
 *
 * Cross-references:
 *   Adapter HTTP client:  packages/alphaclaw-adapter/src/index.js
 *   Local agent client:   packages/local-agents/src/orchestrator.js
 *   Migration log:        docs/MIGRATION.md Gate 2
 *   API surface:          docs/adapter-interface-contract.md
 *   OpenClaw plan:        docs/plans/2026-05-22-alphaclaw-wiring-migration-v2-satellites.md
 */

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// AlphaClaw project root — PT drives AlphaClaw externally via CLI/HTTP only, NEVER require()
const PROJECT_ROOT =
  process.env.ALPHACLAW_ROOT ||
  path.resolve(__dirname, "..", "..", "..", "..", "AlphaClaw");
const OPENCLAW_DIR = path.join(PROJECT_ROOT, ".openclaw");
const CONFIG_PATH = path.join(OPENCLAW_DIR, "openclaw.json");
const ENV_PATH = path.join(PROJECT_ROOT, ".env");

// ─── Secret redactor ─────────────────────────────────────────────────────────
// Preserves arrays (P2 fix: Object.fromEntries on an array produces numeric-keyed object)

const REDACT_KEYS = /token|secret|password|key|auth|credential/i;

function redact(obj: unknown): unknown {
  if (Array.isArray(obj)) return obj.map(redact);
  if (!obj || typeof obj !== "object") return obj;
  return Object.fromEntries(
    Object.entries(obj as Record<string, unknown>).map(([k, v]) => [
      k,
      REDACT_KEYS.test(k) ? "[REDACTED]" : redact(v),
    ])
  );
}

// ─── File-based tool implementations ─────────────────────────────────────────

function readConfig(): { configured: boolean; config?: unknown; message?: string; error?: string } {
  if (!fs.existsSync(CONFIG_PATH)) {
    return { configured: false, message: "openclaw.json not found — run setup first." };
  }
  try {
    const raw = JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8"));
    return { configured: true, config: redact(raw) };
  } catch (e: any) {
    return { configured: false, error: e.message };
  }
}

function listProviders(): unknown {
  const cfg = readConfig();
  if (!cfg.configured) return cfg;
  const providers =
    (cfg.config as any)?.gateway?.providers ||
    (cfg.config as any)?.providers ||
    {};
  return {
    providers: Object.entries(providers as Record<string, any>).map(([name, info]) => ({
      name,
      enabled: info?.enabled !== false,
      models: info?.models || [],
    })),
  };
}

function tailLogs(lines = 50): unknown {
  // P2 fix: guard against negative, NaN, or Infinity inputs
  const raw = Number(lines);
  const cap = Number.isFinite(raw) && raw > 0 ? Math.min(Math.floor(raw), 200) : 50;
  const logPath = path.join(OPENCLAW_DIR, "hourly-sync.log");
  if (!fs.existsSync(logPath)) {
    return { found: false, message: `Log not found at ${logPath}` };
  }
  try {
    const content = fs.readFileSync(logPath, "utf8");
    const tail = content.trim().split("\n").slice(-cap).join("\n");
    return { found: true, lines: cap, log: tail };
  } catch (e: any) {
    return { found: false, error: e.message };
  }
}

function checkEnv(): unknown {
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

// ─── Process-spawning tool implementations ────────────────────────────────────

function buildUi(): unknown {
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
  } catch (e: any) {
    return { success: false, error: e.message };
  }
}

function runTests(suite: "full" | "watchdog" | "coverage"): unknown {
  const SUITES: Record<string, string[]> = {
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
  if (!args) return { error: `Unknown suite: ${suite}` };
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
  } catch (e: any) {
    return { suite, success: false, error: e.message };
  }
}

// ─── Helper: wrap any result with structuredContent ───────────────────────────
// MCP 2024-11-05: content[] is required; structuredContent is optional but useful
// for rich tool consumers. Mirrors Gate 0 JS pattern.

function toolResult(result: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
    structuredContent: result,
  };
}

// ─── MCP server ───────────────────────────────────────────────────────────────

const server = new Server(
  { name: "alphaclaw-mcp", version: "0.9.16.9" },
  { capabilities: { tools: {} } }
);

const ALL_TOOL_DEFINITIONS = [
    // ── HTTP/adapter tools ──────────────────────────────────────────────────
    {
      name: "alphaclaw_health",
      description: "Ping the AlphaClaw gateway health endpoint to check liveness. Does not require authentication.",
      inputSchema: { type: "object", properties: {}, required: [] },
      annotations: { readOnlyHint: true, destructiveHint: false },
    },
    {
      name: "alphaclaw_login",
      description: "Login to the AlphaClaw gateway using SETUP_PASSWORD to establish an active session. Required before calling authenticated endpoints.",
      inputSchema: {
        type: "object",
        properties: {
          password: { type: "string", description: "AlphaClaw SETUP_PASSWORD value" },
        },
        required: ["password"],
      },
      annotations: { readOnlyHint: false, destructiveHint: false },
    },
    {
      name: "alphaclaw_status",
      description: "Fetch detailed metrics and stats about the running AlphaClaw gateway via HTTP. Requires gateway to be running.",
      inputSchema: { type: "object", properties: {}, required: [] },
      annotations: { readOnlyHint: true, destructiveHint: false },
    },
    {
      name: "alphaclaw_watchdog_logs",
      description: "Pull recent watchdog observability logs from the AlphaClaw gateway. Requires authentication (call alphaclaw_login first).",
      inputSchema: {
        type: "object",
        properties: {
          lines: { type: "number", description: "Number of recent log rows to return (default 50, max 200)" },
        },
        required: [],
      },
      annotations: { readOnlyHint: true, destructiveHint: false },
    },

    // ── File-based tools ────────────────────────────────────────────────────
    {
      name: "alphaclaw_read_config",
      description: "Read the current openclaw.json configuration from disk. Secrets (tokens, passwords, keys) are redacted. Returns provider list, channel config, and gateway settings.",
      inputSchema: { type: "object", properties: {}, required: [] },
      annotations: { readOnlyHint: true, destructiveHint: false },
    },
    {
      name: "alphaclaw_list_providers",
      description: "List all AI model providers configured in openclaw.json with their model arrays and enabled state. Works without a running gateway.",
      inputSchema: { type: "object", properties: {}, required: [] },
      annotations: { readOnlyHint: true, destructiveHint: false },
    },
    {
      name: "alphaclaw_tail_logs",
      description: "Return the last N lines from the AlphaClaw hourly-sync log. Works without a running gateway.",
      inputSchema: {
        type: "object",
        properties: {
          lines: { type: "number", description: "Number of log lines to return (default 50, max 200)" },
        },
        required: [],
      },
      annotations: { readOnlyHint: true, destructiveHint: false },
    },
    {
      name: "alphaclaw_check_env",
      description: "Verify the .env file exists in the AlphaClaw project root and that SETUP_PASSWORD is set. Returns status without revealing the password value.",
      inputSchema: { type: "object", properties: {}, required: [] },
      annotations: { readOnlyHint: true, destructiveHint: false },
    },

    // ── Process-spawning tools ──────────────────────────────────────────────
    {
      name: "alphaclaw_build_ui",
      description: "Run `npm run build:ui` in the AlphaClaw project and return stdout/stderr. Use to verify esbuild ARM64 compatibility on macOS.",
      inputSchema: { type: "object", properties: {}, required: [] },
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true },
    },
    {
      name: "alphaclaw_run_tests",
      description: "Run the AlphaClaw Vitest test suite and return pass/fail summary. suite: 'full' (all tests), 'watchdog' (14 watchdog tests), 'coverage' (with lcov).",
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
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true },
    },

    // ── Local agent tools ───────────────────────────────────────────────────
    {
      name: "local_agent_health",
      description: "Check which local AI agents are reachable: Ollama at 127.0.0.1:11435 and LM Studio at the LAN Windows GPU host. Call before delegating tasks to verify availability.",
      inputSchema: { type: "object", properties: {}, required: [] },
      annotations: { readOnlyHint: true, destructiveHint: false },
    },
    {
      name: "local_agent_list_models",
      description: "List all AI models available across Ollama and LM Studio backends. Returns model names grouped by backend.",
      inputSchema: { type: "object", properties: {}, required: [] },
      annotations: { readOnlyHint: true, destructiveHint: false },
    },
    {
      name: "local_agent_ask_about_code",
      description: "Delegate a code question to a local AI agent (Ollama or LM Studio). The agent reads the specified file and answers. Claude acts as planner/reviewer; local agent does the heavy lifting. Good for: understanding a file, finding a bug location, summarizing logic.",
      inputSchema: {
        type: "object",
        properties: {
          filePath: {
            type: "string",
            description: "Path to the file to analyze (relative to AlphaClaw project root or absolute)",
          },
          question: {
            type: "string",
            description: "What to ask about the file (e.g. 'Where is the SETUP_PASSWORD check?')",
          },
          backend: {
            type: "string",
            enum: ["ollama", "lmstudio"],
            description: "Force a specific backend (optional — auto-selects best available)",
          },
        },
        required: ["filePath", "question"],
      },
      annotations: { readOnlyHint: true, destructiveHint: false },
    },
    {
      name: "local_agent_propose_edit",
      description: "Ask a local AI agent to propose a code edit as a unified diff. The patch is returned for Claude to review — it is NOT applied automatically. Claude must validate and approve before any write. Good for: targeted bug fixes, variable renames, adding error handling.",
      inputSchema: {
        type: "object",
        properties: {
          filePath: {
            type: "string",
            description: "Path to the file to edit (relative to AlphaClaw project root or absolute)",
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
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false },
    },
];

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: ALL_TOOL_DEFINITIONS.filter((t) => isToolAllowed(t.name)),
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const toolName = request.params.name;
  if (!isToolAllowed(toolName)) {
    throw new McpError(ErrorCode.InvalidRequest, toolDisabledMessage(toolName));
  }
  try {
    switch (toolName) {
      // ── HTTP/adapter tools ────────────────────────────────────────────────
      case "alphaclaw_health":
        return toolResult(await adapter.health());

      case "alphaclaw_login": {
        const password = String(request.params.arguments?.password ?? "");
        if (!password) throw new McpError(ErrorCode.InvalidParams, "Password required.");
        return toolResult(await adapter.login(password));
      }

      case "alphaclaw_status":
        return toolResult(await adapter.status());

      case "alphaclaw_watchdog_logs": {
        const lines = request.params.arguments?.lines ? Number(request.params.arguments.lines) : 50;
        return toolResult(await adapter.watchdogLogs(lines));
      }

      // ── File-based tools ──────────────────────────────────────────────────
      case "alphaclaw_read_config":
        return toolResult(readConfig());

      case "alphaclaw_list_providers":
        return toolResult(listProviders());

      case "alphaclaw_tail_logs": {
        const lines = request.params.arguments?.lines ? Number(request.params.arguments.lines) : 50;
        return toolResult(tailLogs(lines));
      }

      case "alphaclaw_check_env":
        return toolResult(checkEnv());

      // ── Process-spawning tools ────────────────────────────────────────────
      case "alphaclaw_build_ui":
        return toolResult(buildUi());

      case "alphaclaw_run_tests": {
        const suite = String(request.params.arguments?.suite ?? "full") as
          | "full"
          | "watchdog"
          | "coverage";
        return toolResult(runTests(suite));
      }

      // ── Local agent tools ─────────────────────────────────────────────────
      case "local_agent_health":
        return toolResult(await orchestrator.checkAgentHealth());

      case "local_agent_list_models":
        return toolResult(await orchestrator.listLocalModels());

      case "local_agent_ask_about_code": {
        const filePath = String(request.params.arguments?.filePath ?? "");
        const question = String(request.params.arguments?.question ?? "");
        const backend = request.params.arguments?.backend
          ? String(request.params.arguments.backend)
          : undefined;
        return toolResult(await orchestrator.delegateCodeQuestion({ filePath, question, backend }));
      }

      case "local_agent_propose_edit": {
        const filePath = String(request.params.arguments?.filePath ?? "");
        const instruction = String(request.params.arguments?.instruction ?? "");
        const backend = request.params.arguments?.backend
          ? String(request.params.arguments.backend)
          : undefined;
        return toolResult(await orchestrator.delegateCodeEdit({ filePath, instruction, backend }));
      }

      default:
        throw new McpError(ErrorCode.MethodNotFound, `Unknown tool: ${request.params.name}`);
    }
  } catch (err: any) {
    return {
      content: [{ type: "text" as const, text: `Error: ${err.message}` }],
      isError: true,
    };
  }
});

async function run() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  const visible = ALL_TOOL_DEFINITIONS.filter((t) => isToolAllowed(t.name)).length;
  console.error(
    `AlphaClaw MCP Server v0.9.16.9 started on stdio (${visible}/${ALL_TOOL_DEFINITIONS.length} tools — ${profileStartupSummary()})`
  );
}

run().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
