"use strict";

const { describe, it, beforeEach, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const path = require("path");

const profilesPath = path.join(__dirname, "..", "build", "mcp-profiles.js");

describe("mcp-profiles", () => {
  let envSnapshot;

  beforeEach(() => {
    envSnapshot = {
      ALPHACLAW_MCP_PROFILE: process.env.ALPHACLAW_MCP_PROFILE,
      ALPHACLAW_MCP_ENABLE_PROCESS_TOOLS: process.env.ALPHACLAW_MCP_ENABLE_PROCESS_TOOLS,
      ALPHACLAW_MCP_ENABLE_MUTATING_TOOLS: process.env.ALPHACLAW_MCP_ENABLE_MUTATING_TOOLS,
    };
    delete process.env.ALPHACLAW_MCP_PROFILE;
    delete process.env.ALPHACLAW_MCP_ENABLE_PROCESS_TOOLS;
    delete process.env.ALPHACLAW_MCP_ENABLE_MUTATING_TOOLS;
  });

  afterEach(() => {
    for (const [key, value] of Object.entries(envSnapshot)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  });

  it("loads from build output", async () => {
    const mod = await import(profilesPath);
    assert.equal(typeof mod.isToolAllowed, "function");
    assert.equal(typeof mod.profileStartupSummary, "function");
    assert.equal(typeof mod.toolDisabledMessage, "function");
  });

  it("readonly profile blocks process tools by default", async () => {
    const { isToolAllowed } = await import(profilesPath);
    assert.equal(isToolAllowed("alphaclaw_health"), true);
    assert.equal(isToolAllowed("alphaclaw_build_ui"), false);
    assert.equal(isToolAllowed("local_agent_propose_edit"), false);
  });

  it("elevated profile allows all tools", async () => {
    process.env.ALPHACLAW_MCP_PROFILE = "elevated";
    const { isToolAllowed } = await import(profilesPath);
    assert.equal(isToolAllowed("alphaclaw_build_ui"), true);
    assert.equal(isToolAllowed("local_agent_propose_edit"), true);
  });
});
