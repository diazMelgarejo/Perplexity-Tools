#!/usr/bin/env node
/**
 * alphaclaw-mcp — MCP server for AlphaClaw
 *
 * Exposes AlphaClaw server controls and config as MCP tools so
 * Xcode 26+ / Claude Code can manage AlphaClaw directly.
 *
 * Home: packages/alphaclaw-adapter/src/mcp/server.js (Perpetua-Tools)
 * Origin: moved from AlphaClaw lib/mcp/alphaclaw-mcp.js — v0.9.9.8
 *
 * Transport: stdio (local integration, no network auth needed)
 * Register:  claude mcp add --transport stdio alphaclaw -- node packages/alphaclaw-adapter/src/mcp/server.js
 *
 * IMPORTANT: This server drives AlphaClaw via its CLI/HTTP surface only.
 * It NEVER require()s AlphaClaw internals. All AlphaClaw interaction is
 * via spawned processes or HTTP calls to the running AlphaClaw server.
 *
 * Tools:
 *   alphaclaw_status              — check if server is running + port
 *   alphaclaw_read_config         — read openclaw.json (sanitized, no secrets)
 *   alphaclaw_tail_logs           — last N lines of alphaclaw stdout log
 *   alphaclaw_list_providers      — list configured AI providers
 *   alphaclaw_check_env           — check .env / SETUP_PASSWORD presence
 *   alphaclaw_build_ui            — run npm run build:ui and return output
 *   alphaclaw_run_tests           — run npm test / test:watchdog and return results
 *   local_agent_health            — check Ollama + LM Studio reachability
 *   local_agent_list_models       — list all models across local backends
 *   local_agent_ask_about_code    — delegate code question to local agent
 *   local_agent_propose_edit      — ask local agent to propose a code patch (Claude reviews)
 */

"use strict";

const { execSync, spawnSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const readline = require("readline");

// ─── AlphaClaw project root — PT drives AlphaClaw externally ─────────────────
// Default: sibling directory. Override with ALPHACLAW_ROOT env var.
const PROJECT_ROOT = process.env.ALPHACLAW_ROOT
  || path.resolve(__dirname, "..", "..", "..", "..", "..", "AlphaClaw");
const OPENCLAW_DIR = path.join(PROJECT_ROOT, ".openclaw");
const CONFIG_PATH = path.join(OPENCLAW_DIR, "openclaw.json");
const ENV_PATH = path.join(PROJECT_ROOT, ".env");

// ─── Local agent orchestrator (lazy require — survives missing deps gracefully) ─
// In PT, orchestrator lives at packages/local-agents/src/orchestrator.js
let _orchestrator = null;
function getOrchestrator() {
  if (!_orchestrator) {
    try {
      _orchestrator = require("../../../local-agents/src/orchestrator");
    } catch (e) {
      throw new Error(`Local agent orchestrator not available: ${e.message}`);
    }
  }
  return _orchestrator;
}

// ─── MCP stdio protocol helpers ───────────────────────────────────────────────
const send = (obj) => process.stdout.write(JSON.stringify(obj) + "\n");

const TOOLS = [
  {
    name: "alphaclaw_status",
    description:
      "Check whether the AlphaClaw server is running and on which port. Returns process info and port.",
    inputSchema: { type: "object", properties: {}, required: [] },
    annotations: { readOnlyHint: true, destructiveHint: false },
  },
  {
    name: "alphaclaw_read_config",
    description:
      "Read the current openclaw.json configuration. Secrets (tokens, passwords) are redacted. Returns provider list, channel config, and gateway settings.",
    inputSchema: { type: "object", properties: {}, required: [] },
    annotations: { readOnlyHint: true, destructiveHint: false },
  },
  {
    name: "alphaclaw_list_providers",
    description:
      "List all AI model providers configured in openclaw.json with their model arrays and enabled state.",
    inputSchema: { type: "object", properties: {}, required: [] },
    annotations: { readOnlyHint: true, destructiveHint: false },
  },
  {
    name: "alphaclaw_tail_logs",
    description:
      "Return the last N lines from the AlphaClaw hourly-sync log or npm start output.",
    inputSchema: {
      type: "object",
      properties: {
        lines: {
          type: "number",
          description: "Number of log lines to return (default 50, max 200)",
        },
      },
      required: [],
    },
    annotations: { readOnlyHint: true, destructiveHint: false },
  },
  {
    name: "alphaclaw_check_env",
    description:
      "Verify .env file exists and SETUP_PASSWORD is set. Returns status without revealing the password value.",
    inputSchema: { type: "object", properties: {}, required: [] },
    annotations: { readOnlyHint: true, destructiveHint: false },
  },
  {
    name: "alphaclaw_build_ui",
    description:
      "Run `npm run build:ui` in the AlphaClaw project and return stdout/stderr. Use to verify esbuild ARM64 compatibility.",
    inputSchema: { type: "object", properties: {}, required: [] },
    annotations: {
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
    },
  },
  {
    name: "alphaclaw_run_tests",
    description:
      "Run AlphaClaw test suite. suite can be 'full' (440 tests), 'watchdog' (14 tests), or 'coverage'. Returns pass/fail summary.",
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
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
    },
  },

  // ── Local agent tools ─────────────────────────────────────────────────────
  {
    name: "local_agent_health",
    description:
      "Check which local AI agents (Ollama at 127.0.0.1:11435, LM Studio at 192.168.254.101:1234) are reachable and which models are loaded. Use this before delegating tasks to verify availability.",
    inputSchema: { type: "object", properties: {}, required: [] },
    annotations: { readOnlyHint: true, destructiveHint: false },
  },
  {
    name: "local_agent_list_models",
    description:
      "List all AI models available across Ollama and LM Studio. Returns model names per backend.",
    inputSchema: { type: "object", properties: {}, required: [] },
    annotations: { readOnlyHint: true, destructiveHint: false },
  },
  {
    name: "local_agent_ask_about_code",
    description:
      "Delegate a code question to a local AI agent (Ollama/LM Studio). The agent reads the specified file and answers the question. Claude acts as planner/reviewer; the local agent does the reading. Good for: understanding a file, finding a bug location, summarizing logic.",
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
    annotations: { readOnlyHint: true, destructiveHint: false },
  },
  {
    name: "local_agent_propose_edit",
    description:
      "Ask a local AI agent to propose a code edit as a unified diff. The patch is returned for Claude to review — it is NOT applied automatically. Claude must validate and approve before any changes are written. Good for: targeted bug fixes, variable renames, adding error handling.",
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
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false },
  },
];

// ─── Tool implementations ─────────────────────────────────────────────────────

function alphaclaw_status() {
  try {
    // Check for node process running alphaclaw.js
    const result = spawnSync(
      "pgrep",
      ["-f", "alphaclaw.js"],
      { encoding: "utf8" }
    );
    const pids = (result.stdout || "").trim().split("\n").filter(Boolean);
    if (pids.length === 0) {
      return { running: false, message: "AlphaClaw server is not running." };
    }
    // Try to read port from env or default
    const port = process.env.PORT || 3000;
    return {
      running: true,
      pids,
      port,
      url: `http://localhost:${port}`,
      message: `AlphaClaw running (PID ${pids.join(", ")}) on port ${port}`,
    };
  } catch (e) {
    return { running: false, error: e.message };
  }
}

function alphaclaw_read_config() {
  if (!fs.existsSync(CONFIG_PATH)) {
    return { configured: false, message: "openclaw.json not found — run setup first." };
  }
  try {
    const raw = JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8"));
    // Redact secrets
    const redact = (obj) => {
      if (!obj || typeof obj !== "object") return obj;
      const REDACT_KEYS = /token|secret|password|key|auth|credential/i;
      return Object.fromEntries(
        Object.entries(obj).map(([k, v]) => [
          k,
          REDACT_KEYS.test(k)
            ? "[REDACTED]"
            : typeof v === "object"
            ? redact(v)
            : v,
        ])
      );
    };
    return { configured: true, config: redact(raw) };
  } catch (e) {
    return { configured: false, error: e.message };
  }
}

function alphaclaw_list_providers() {
  const cfg = alphaclaw_read_config();
  if (!cfg.configured) return cfg;
  const providers = cfg.config?.gateway?.providers || cfg.config?.providers || {};
  return {
    providers: Object.entries(providers).map(([name, info]) => ({
      name,
      enabled: info?.enabled !== false,
      models: info?.models || [],
    })),
  };
}

function alphaclaw_tail_logs({ lines = 50 } = {}) {
  const cap = Math.min(lines, 200);
  const logPath = path.join(OPENCLAW_DIR, "hourly-sync.log");
  if (!fs.existsSync(logPath)) {
    return { found: false, message: `Log not found at ${logPath}` };
  }
  try {
    const content = fs.readFileSync(logPath, "utf8");
    const tail = content.trim().split("\n").slice(-cap).join("\n");
    return { found: true, lines: cap, log: tail };
  } catch (e) {
    return { found: false, error: e.message };
  }
}

function alphaclaw_check_env() {
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

function alphaclaw_build_ui() {
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
  } catch (e) {
    return { success: false, error: e.message };
  }
}

function alphaclaw_run_tests({ suite }) {
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
  if (!args) return { error: `Unknown suite: ${suite}` };

  try {
    const result = spawnSync(
      "./node_modules/.bin/vitest",
      args,
      { cwd: PROJECT_ROOT, encoding: "utf8", timeout: 120000 }
    );
    const output = (result.stdout || "") + (result.stderr || "");
    // Extract summary line
    const summaryMatch = output.match(/Tests?\s+\d+[^\n]*/i);
    return {
      suite,
      exit_code: result.status,
      success: result.status === 0,
      summary: summaryMatch ? summaryMatch[0].trim() : "see output",
      output: output.slice(-4000),
    };
  } catch (e) {
    return { suite, success: false, error: e.message };
  }
}

// ─── Local agent tool implementations ────────────────────────────────────────

async function local_agent_health() {
  try {
    const orch = getOrchestrator();
    return await orch.checkAgentHealth();
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

async function local_agent_list_models() {
  try {
    const orch = getOrchestrator();
    return await orch.listLocalModels();
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

async function local_agent_ask_about_code({ filePath, question, backend }) {
  try {
    const orch = getOrchestrator();
    return await orch.delegateCodeQuestion({ filePath, question, backend });
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

async function local_agent_propose_edit({ filePath, instruction, backend }) {
  try {
    const orch = getOrchestrator();
    return await orch.delegateCodeEdit({ filePath, instruction, backend });
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

// ─── MCP stdio message loop ───────────────────────────────────────────────────

const DISPATCH = {
  alphaclaw_status,
  alphaclaw_read_config,
  alphaclaw_list_providers,
  alphaclaw_tail_logs,
  alphaclaw_check_env,
  alphaclaw_build_ui,
  alphaclaw_run_tests,
  local_agent_health,
  local_agent_list_models,
  local_agent_ask_about_code,
  local_agent_propose_edit,
};

const rl = readline.createInterface({ input: process.stdin, terminal: false });

rl.on("line", (line) => {
  let msg;
  try {
    msg = JSON.parse(line);
  } catch {
    return;
  }

  const { id, method, params } = msg;

  if (method === "initialize") {
    send({
      jsonrpc: "2.0", id,
      result: {
        protocolVersion: "2024-11-05",
        serverInfo: { name: "alphaclaw-mcp", version: "0.9.9.7" },
        capabilities: { tools: {} },
      },
    });
    return;
  }

  if (method === "tools/list") {
    send({ jsonrpc: "2.0", id, result: { tools: TOOLS } });
    return;
  }

  if (method === "tools/call") {
    const { name, arguments: args } = params || {};
    const fn = DISPATCH[name];
    if (!fn) {
      send({
        jsonrpc: "2.0", id,
        error: { code: -32601, message: `Unknown tool: ${name}` },
      });
      return;
    }
    // All tool functions may be sync or async — always await
    Promise.resolve()
      .then(() => fn(args || {}))
      .then((result) => {
        send({
          jsonrpc: "2.0", id,
          result: {
            content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
            structuredContent: result,
          },
        });
      })
      .catch((e) => {
        send({
          jsonrpc: "2.0", id,
          error: { code: -32603, message: e.message },
        });
      });
    return;
  }

  // Unknown method
  send({
    jsonrpc: "2.0", id,
    error: { code: -32601, message: `Method not found: ${method}` },
  });
});

rl.on("close", () => process.exit(0));
