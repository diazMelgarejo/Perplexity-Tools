/**
 * Security fix 6 — MCP profile gates.
 * Run: node --test packages/alphaclaw-mcp/tests/mcp-profiles.test.mjs
 * (from repo root after: cd packages/alphaclaw-mcp && npm run build)
 */

import { describe, it, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PKG_ROOT = path.resolve(__dirname, "..");
const BUILD_PROFILES = path.join(PKG_ROOT, "build", "mcp-profiles.js");

const {
  resolveMcpProfile,
  isToolAllowed,
  processToolsEnabled,
  mutatingToolsEnabled,
  READONLY_TOOL_NAMES,
  PROCESS_TOOL_NAMES,
  MUTATING_TOOL_NAMES,
} = await import(BUILD_PROFILES);

const ENV_KEYS = [
  "ALPHACLAW_MCP_PROFILE",
  "ALPHACLAW_MCP_ENABLE_PROCESS_TOOLS",
  "ALPHACLAW_MCP_ENABLE_MUTATING_TOOLS",
];

function snapshotEnv() {
  const snap = {};
  for (const k of ENV_KEYS) snap[k] = process.env[k];
  return snap;
}

function restoreEnv(snap) {
  for (const k of ENV_KEYS) {
    if (snap[k] === undefined) delete process.env[k];
    else process.env[k] = snap[k];
  }
}

describe("mcp-profiles", () => {
  let envSnap;

  beforeEach(() => {
    envSnap = snapshotEnv();
    delete process.env.ALPHACLAW_MCP_PROFILE;
    delete process.env.ALPHACLAW_MCP_ENABLE_PROCESS_TOOLS;
    delete process.env.ALPHACLAW_MCP_ENABLE_MUTATING_TOOLS;
  });

  afterEach(() => restoreEnv(envSnap));

  it("defaults to readonly profile", () => {
    assert.equal(resolveMcpProfile(), "readonly");
  });

  it("readonly allows read-only tools only", () => {
    for (const name of READONLY_TOOL_NAMES) {
      assert.equal(isToolAllowed(name), true, name);
    }
    for (const name of [...PROCESS_TOOL_NAMES, ...MUTATING_TOOL_NAMES]) {
      assert.equal(isToolAllowed(name), false, name);
    }
  });

  it("elevated profile enables all tools", () => {
    process.env.ALPHACLAW_MCP_PROFILE = "elevated";
    for (const name of [
      ...READONLY_TOOL_NAMES,
      ...PROCESS_TOOL_NAMES,
      ...MUTATING_TOOL_NAMES,
    ]) {
      assert.equal(isToolAllowed(name), true, name);
    }
  });

  it("granular process flag without elevated profile", () => {
    process.env.ALPHACLAW_MCP_ENABLE_PROCESS_TOOLS = "1";
    assert.equal(processToolsEnabled(), true);
    assert.equal(mutatingToolsEnabled(), false);
    assert.equal(isToolAllowed("alphaclaw_build_ui"), true);
    assert.equal(isToolAllowed("alphaclaw_login"), false);
  });

  it("granular mutating flag without elevated profile", () => {
    process.env.ALPHACLAW_MCP_ENABLE_MUTATING_TOOLS = "yes";
    assert.equal(mutatingToolsEnabled(), true);
    assert.equal(isToolAllowed("local_agent_propose_edit"), true);
    assert.equal(isToolAllowed("alphaclaw_run_tests"), false);
  });
});

describe("index.ts list filter integration", () => {
  it("build output exists", () => {
    const r = spawnSync("npm", ["run", "build"], { cwd: PKG_ROOT, encoding: "utf8" });
    assert.equal(r.status, 0, r.stderr || r.stdout);
  });
});
