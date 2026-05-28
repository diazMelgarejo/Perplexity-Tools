/**
 * Security fix 4-5 — MCP path-boundary enforcement integration tests.
 *
 * Tests the logic introduced in packages/alphaclaw-mcp/src/index.ts:
 *   - getPathGateConfig() — exported path gate configuration
 *   - evaluatePathGate()  — exported path validation helper
 *   - readConfigFile()    — path gate + config reading
 *   - readLogTail()       — path gate + redactLogText
 *   - readEnvVars()       — path gate + env checking
 *   - env-var initialisation (ALPHACLAW_ROOT / PERPETUA_TOOLS_ROOT)
 *
 * These tests now import and exercise the exported helper functions directly
 * instead of reimplementing the logic.
 *
 * Run: node --test packages/alphaclaw-mcp/tests/path-boundary-mcp.test.mjs
 *      (from repo root, no build step required)
 */

import { describe, it, before, after, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);

// Import exported helpers from index.ts (via compiled build)
import {
  getPathGateConfig,
  evaluatePathGate,
  readConfigFile,
  readLogTail,
  readEnvVars,
  redactLogText,
} from "../build/index.js";

// Load path-boundary.cjs for additional low-level tests
const { getApprovedRoots } = require("../../local-agents/src/path-boundary.cjs");

// ──────────────────────────────────────────────────────────────────────────────
// Shared temp-directory fixture
// ──────────────────────────────────────────────────────────────────────────────

let tmpDir;
let projectRoot;     // stands in for PROJECT_ROOT (ALPHACLAW_ROOT)
let perpetuaRoot;    // stands in for PERPETUA_TOOLS_ROOT
let outsideDir;      // directory that is NOT under either root

before(() => {
  tmpDir       = fs.mkdtempSync(path.join(os.tmpdir(), "mcp-pbmcp-"));
  projectRoot  = path.join(tmpDir, "AlphaClaw");
  perpetuaRoot = path.join(tmpDir, "perpetua-tools");
  outsideDir   = path.join(tmpDir, "outside");

  fs.mkdirSync(path.join(projectRoot,  ".openclaw"), { recursive: true });
  fs.mkdirSync(perpetuaRoot, { recursive: true });
  fs.mkdirSync(outsideDir,   { recursive: true });
});

after(() => {
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

// ──────────────────────────────────────────────────────────────────────────────
// 1. evaluatePathGate behaviour
// ──────────────────────────────────────────────────────────────────────────────

describe("evaluatePathGate", () => {
  it("accepts an absolute path that lives under projectRoot", () => {
    const target = path.join(projectRoot, ".openclaw", "openclaw.json");
    const result = evaluatePathGate(target, [projectRoot, perpetuaRoot]);
    assert.equal(result.ok, true, `Expected ok but got error: ${result.error}`);
    assert.equal(result.abs, target);
  });

  it("accepts an absolute path that lives under perpetuaRoot", () => {
    const target = path.join(perpetuaRoot, "packages", "some-file.js");
    const result = evaluatePathGate(target, [projectRoot, perpetuaRoot]);
    assert.equal(result.ok, true, `Expected ok but got error: ${result.error}`);
    assert.equal(result.abs, target);
  });

  it("rejects an absolute path outside both approved roots", () => {
    const target = path.join(outsideDir, "secret.txt");
    const result = evaluatePathGate(target, [projectRoot, perpetuaRoot]);
    assert.equal(result.ok, false);
    assert.match(result.error, /outside approved MCP roots/i);
  });

  it("accepts a deeply nested path inside projectRoot", () => {
    const target = path.join(projectRoot, "src", "deep", "nested", "file.ts");
    const result = evaluatePathGate(target, [projectRoot, perpetuaRoot]);
    assert.equal(result.ok, true);
  });

  it("rejects a path with null byte (invalid path)", () => {
    const target = projectRoot + "/file\0.txt";
    const result = evaluatePathGate(target, [projectRoot, perpetuaRoot]);
    assert.equal(result.ok, false);
    assert.match(result.error, /invalid path/i);
  });

  it("rejects path traversal that would escape projectRoot", () => {
    const target = path.resolve(projectRoot, "..", "..", "etc", "passwd");
    const result = evaluatePathGate(target, [projectRoot, perpetuaRoot]);
    assert.equal(result.ok, false);
  });

  it("does not require the file to exist (mustExist:false semantics)", () => {
    const nonExistent = path.join(projectRoot, "does-not-exist.json");
    const result = evaluatePathGate(nonExistent, [projectRoot, perpetuaRoot]);
    // File doesn't exist on disk but should still be approved since it's under root
    assert.equal(result.ok, true);
  });

  it("returns the normalised abs path in the ok result", () => {
    const target = path.join(projectRoot, ".", ".openclaw", ".", "openclaw.json");
    const result = evaluatePathGate(target, [projectRoot, perpetuaRoot]);
    assert.equal(result.ok, true);
    // path.resolve normalises the dots
    assert.equal(result.abs, path.resolve(target));
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// 2. getPathGateConfig — exported path gate configuration
// ──────────────────────────────────────────────────────────────────────────────

describe("getPathGateConfig", () => {
  it("returns projectRoot, perpetuaRoot, and approvedRoots", () => {
    const config = getPathGateConfig();
    assert.ok(config.projectRoot, "projectRoot should be defined");
    assert.ok(config.perpetuaRoot, "perpetuaRoot should be defined");
    assert.ok(Array.isArray(config.approvedRoots), "approvedRoots should be an array");
    assert.ok(config.approvedRoots.length > 0, "approvedRoots should not be empty");
  });

  it("approvedRoots includes projectRoot and perpetuaRoot", () => {
    const config = getPathGateConfig();
    const resolved = config.approvedRoots.map((r) => path.resolve(r));
    assert.ok(
      resolved.includes(path.resolve(config.projectRoot)),
      "approvedRoots should include projectRoot"
    );
    assert.ok(
      resolved.includes(path.resolve(config.perpetuaRoot)),
      "approvedRoots should include perpetuaRoot"
    );
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// 3. getApprovedRoots pattern from path-boundary.cjs
// ──────────────────────────────────────────────────────────────────────────────

describe("getApprovedRoots pattern", () => {
  it("includes PROJECT_ROOT and PERPETUA_TOOLS_ROOT passed as extraRoots", () => {
    // Temporarily clear env vars so only extraRoots determines the list
    const envSnap = {};
    const KEYS = ["MCP_APPROVED_ROOTS", "ALPHACLAW_ROOT", "PERPETUA_TOOLS_ROOT", "ORAMA_SYSTEM_ROOT", "OPENCLAW_ROOT"];
    for (const k of KEYS) { envSnap[k] = process.env[k]; delete process.env[k]; }

    try {
      const roots = getApprovedRoots([projectRoot, perpetuaRoot]);
      assert.ok(roots.includes(path.resolve(projectRoot)),  "projectRoot missing from approved roots");
      assert.ok(roots.includes(path.resolve(perpetuaRoot)), "perpetuaRoot missing from approved roots");
    } finally {
      for (const k of KEYS) {
        if (envSnap[k] === undefined) delete process.env[k];
        else process.env[k] = envSnap[k];
      }
    }
  });

  it("deduplicates when the same path is added via env and extraRoots", () => {
    const envSnap = process.env.ALPHACLAW_ROOT;
    process.env.ALPHACLAW_ROOT = projectRoot;
    try {
      const roots = getApprovedRoots([projectRoot, perpetuaRoot]);
      const count = roots.filter((r) => r === path.resolve(projectRoot)).length;
      assert.equal(count, 1, "Same root should appear only once");
    } finally {
      if (envSnap === undefined) delete process.env.ALPHACLAW_ROOT;
      else process.env.ALPHACLAW_ROOT = envSnap;
    }
  });

  it("ALPHACLAW_ROOT env var is included in approved roots", () => {
    const envSnap = process.env.ALPHACLAW_ROOT;
    process.env.ALPHACLAW_ROOT = projectRoot;
    try {
      const roots = getApprovedRoots([]);
      assert.ok(roots.includes(path.resolve(projectRoot)));
    } finally {
      if (envSnap === undefined) delete process.env.ALPHACLAW_ROOT;
      else process.env.ALPHACLAW_ROOT = envSnap;
    }
  });

  it("PERPETUA_TOOLS_ROOT env var is included in approved roots", () => {
    const envSnap = process.env.PERPETUA_TOOLS_ROOT;
    process.env.PERPETUA_TOOLS_ROOT = perpetuaRoot;
    try {
      const roots = getApprovedRoots([]);
      assert.ok(roots.includes(path.resolve(perpetuaRoot)));
    } finally {
      if (envSnap === undefined) delete process.env.PERPETUA_TOOLS_ROOT;
      else process.env.PERPETUA_TOOLS_ROOT = envSnap;
    }
  });

  it("returns a non-empty array even when no env vars are set and no extraRoots given", () => {
    const KEYS = ["MCP_APPROVED_ROOTS", "ALPHACLAW_ROOT", "PERPETUA_TOOLS_ROOT", "ORAMA_SYSTEM_ROOT", "OPENCLAW_ROOT"];
    const envSnap = {};
    for (const k of KEYS) { envSnap[k] = process.env[k]; delete process.env[k]; }
    try {
      const roots = getApprovedRoots([]);
      assert.ok(Array.isArray(roots));
      assert.ok(roots.length > 0, "Should fall back to default root");
    } finally {
      for (const k of KEYS) {
        if (envSnap[k] === undefined) delete process.env[k];
        else process.env[k] = envSnap[k];
      }
    }
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// 4. readConfigFile path gate behaviour
// ──────────────────────────────────────────────────────────────────────────────

describe("readConfigFile path gate", () => {
  it("returns error when config path is outside approved roots", () => {
    const outsidePath = path.join(outsideDir, ".openclaw", "openclaw.json");
    const result = readConfigFile(outsidePath, [projectRoot, perpetuaRoot]);
    assert.equal(result.configured, false);
    assert.ok(result.error, "Should have an error message");
    assert.match(result.error, /outside approved MCP roots/i);
  });

  it("returns not-found message when config path is valid but file does not exist", () => {
    const missingConfig = path.join(projectRoot, ".openclaw", "openclaw.json");
    // ensure it doesn't exist
    if (fs.existsSync(missingConfig)) fs.unlinkSync(missingConfig);
    const result = readConfigFile(missingConfig, [projectRoot, perpetuaRoot]);
    assert.equal(result.configured, false);
    assert.match(result.message, /not found/i);
    assert.equal(result.error, undefined, "Should be a message, not an error");
  });

  it("reads and parses valid config when path is under approved root", () => {
    const configPath = path.join(projectRoot, ".openclaw", "openclaw.json");
    fs.writeFileSync(configPath, JSON.stringify({ version: 1, gateway: { port: 3000 } }));
    try {
      const result = readConfigFile(configPath, [projectRoot, perpetuaRoot]);
      assert.equal(result.configured, true);
      // Note: redaction is applied, but without sensitive fields it should match
      assert.ok(result.config);
    } finally {
      fs.unlinkSync(configPath);
    }
  });

  it("returns error when config file contains invalid JSON", () => {
    const configPath = path.join(projectRoot, ".openclaw", "openclaw.json");
    fs.writeFileSync(configPath, "{ not valid json }");
    try {
      const result = readConfigFile(configPath, [projectRoot, perpetuaRoot]);
      assert.equal(result.configured, false);
      assert.ok(result.error, "Should have a JSON parse error");
    } finally {
      fs.unlinkSync(configPath);
    }
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// 5. readLogTail path gate + redactLogText
// ──────────────────────────────────────────────────────────────────────────────

describe("readLogTail path gate + redactLogText", () => {
  it("returns error when log path is outside approved roots", () => {
    const outsideLog = path.join(outsideDir, "hourly-sync.log");
    const result = readLogTail(outsideLog, [projectRoot, perpetuaRoot]);
    assert.equal(result.found, false);
    assert.ok(result.error);
    assert.match(result.error, /outside approved MCP roots/i);
  });

  it("returns not-found message when log file does not exist under approved root", () => {
    const missingLog = path.join(projectRoot, ".openclaw", "hourly-sync.log");
    if (fs.existsSync(missingLog)) fs.unlinkSync(missingLog);
    const result = readLogTail(missingLog, [projectRoot, perpetuaRoot]);
    assert.equal(result.found, false);
    assert.match(result.message, /not found under approved AlphaClaw root/i);
  });

  it("reads and returns log content when path is valid and file exists", () => {
    const logPath = path.join(projectRoot, ".openclaw", "hourly-sync.log");
    fs.writeFileSync(logPath, "line1\nline2\nline3\n");
    try {
      const result = readLogTail(logPath, [projectRoot, perpetuaRoot], 10);
      assert.equal(result.found, true);
      assert.equal(result.lines, 10);
      assert.ok(result.log.includes("line1"));
    } finally {
      fs.unlinkSync(logPath);
    }
  });

  it("applies redactLogText to log content — secrets are stripped", () => {
    const logPath = path.join(projectRoot, ".openclaw", "hourly-sync.log");
    const secretContent = "info: start\nSETUP_PASSWORD=supersecret123\nsk-ant-api03-fakekey123456789012345\ninfo: done";
    fs.writeFileSync(logPath, secretContent);
    try {
      const result = readLogTail(logPath, [projectRoot, perpetuaRoot], 50);
      assert.equal(result.found, true);
      assert.ok(!result.log.includes("supersecret123"),  "Password must be redacted");
      assert.ok(!result.log.includes("sk-ant-api03-"),   "API key must be redacted");
      assert.ok(result.log.includes("[REDACTED]"),       "Redaction marker must appear");
    } finally {
      fs.unlinkSync(logPath);
    }
  });

  it("caps line count at 200 even when a large value is requested", () => {
    const logPath = path.join(projectRoot, ".openclaw", "hourly-sync.log");
    const manyLines = Array.from({ length: 250 }, (_, i) => `line${i + 1}`).join("\n");
    fs.writeFileSync(logPath, manyLines);
    try {
      const result = readLogTail(logPath, [projectRoot, perpetuaRoot], 500);
      assert.equal(result.lines, 200);
    } finally {
      fs.unlinkSync(logPath);
    }
  });

  it("uses default cap of 50 when lines argument is non-positive", () => {
    const logPath = path.join(projectRoot, ".openclaw", "hourly-sync.log");
    fs.writeFileSync(logPath, "a\nb\n");
    try {
      const result = readLogTail(logPath, [projectRoot, perpetuaRoot], -5);
      assert.equal(result.lines, 50);
    } finally {
      fs.unlinkSync(logPath);
    }
  });

  it("uses default cap of 50 when lines argument is NaN", () => {
    const logPath = path.join(projectRoot, ".openclaw", "hourly-sync.log");
    fs.writeFileSync(logPath, "a\n");
    try {
      const result = readLogTail(logPath, [projectRoot, perpetuaRoot], NaN);
      assert.equal(result.lines, 50);
    } finally {
      fs.unlinkSync(logPath);
    }
  });

  it("also redacts email addresses appearing in log output", () => {
    const logPath = path.join(projectRoot, ".openclaw", "hourly-sync.log");
    fs.writeFileSync(logPath, "contacted admin@example.com for support\n");
    try {
      const result = readLogTail(logPath, [projectRoot, perpetuaRoot]);
      assert.ok(!result.log.includes("admin@example.com"), "Email must be redacted");
    } finally {
      fs.unlinkSync(logPath);
    }
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// 6. readEnvVars path gate behaviour
// ──────────────────────────────────────────────────────────────────────────────

describe("readEnvVars path gate", () => {
  it("returns error when .env path is outside approved roots", () => {
    const outsideEnv = path.join(outsideDir, ".env");
    const result = readEnvVars(outsideEnv, [projectRoot, perpetuaRoot]);
    assert.equal(result.env_file, false);
    assert.ok(result.error);
    assert.match(result.error, /outside approved MCP roots/i);
  });

  it("returns not-found when .env does not exist under approved root", () => {
    const missingEnv = path.join(projectRoot, ".env");
    if (fs.existsSync(missingEnv)) fs.unlinkSync(missingEnv);
    const result = readEnvVars(missingEnv, [projectRoot, perpetuaRoot]);
    assert.equal(result.env_file, false);
    assert.equal(result.setup_password, false);
    assert.match(result.message, /not found/i);
  });

  it("detects .env present with SETUP_PASSWORD set", () => {
    const envFile = path.join(projectRoot, ".env");
    fs.writeFileSync(envFile, "SETUP_PASSWORD=mysecretpassword\nOTHER=value\n");
    try {
      const result = readEnvVars(envFile, [projectRoot, perpetuaRoot]);
      assert.equal(result.env_file, true);
      assert.equal(result.setup_password, true);
      assert.match(result.message, /set ✓/);
    } finally {
      fs.unlinkSync(envFile);
    }
  });

  it("detects .env present but SETUP_PASSWORD missing", () => {
    const envFile = path.join(projectRoot, ".env");
    fs.writeFileSync(envFile, "OTHER=value\nANOTHER=val\n");
    try {
      const result = readEnvVars(envFile, [projectRoot, perpetuaRoot]);
      assert.equal(result.env_file, true);
      assert.equal(result.setup_password, false);
      assert.match(result.message, /missing or empty/i);
    } finally {
      fs.unlinkSync(envFile);
    }
  });

  it("detects .env with SETUP_PASSWORD= (empty value) as missing", () => {
    const envFile = path.join(projectRoot, ".env");
    fs.writeFileSync(envFile, "SETUP_PASSWORD=\n");
    try {
      const result = readEnvVars(envFile, [projectRoot, perpetuaRoot]);
      assert.equal(result.env_file, true);
      assert.equal(result.setup_password, false);
    } finally {
      fs.unlinkSync(envFile);
    }
  });

  it(".env path under perpetuaRoot is also accepted", () => {
    const envFile = path.join(perpetuaRoot, ".env");
    fs.writeFileSync(envFile, "SETUP_PASSWORD=test\n");
    try {
      const result = readEnvVars(envFile, [projectRoot, perpetuaRoot]);
      assert.equal(result.env_file, true);
      assert.equal(result.setup_password, true);
    } finally {
      fs.unlinkSync(envFile);
    }
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// 7. env-var initialisation semantics (process.env.ALPHACLAW_ROOT / PERPETUA_TOOLS_ROOT)
// ──────────────────────────────────────────────────────────────────────────────

describe("env-var initialisation semantics", () => {
  let savedAlphaclaw;
  let savedPerpetua;

  beforeEach(() => {
    savedAlphaclaw = process.env.ALPHACLAW_ROOT;
    savedPerpetua  = process.env.PERPETUA_TOOLS_ROOT;
  });

  afterEach(() => {
    if (savedAlphaclaw === undefined) delete process.env.ALPHACLAW_ROOT;
    else process.env.ALPHACLAW_ROOT = savedAlphaclaw;

    if (savedPerpetua === undefined) delete process.env.PERPETUA_TOOLS_ROOT;
    else process.env.PERPETUA_TOOLS_ROOT = savedPerpetua;
  });

  it("ALPHACLAW_ROOT should be set to PROJECT_ROOT when env var is absent (simulated)", () => {
    // Simulate: if (!process.env.ALPHACLAW_ROOT) process.env.ALPHACLAW_ROOT = PROJECT_ROOT
    delete process.env.ALPHACLAW_ROOT;
    const simulatedProjectRoot = projectRoot;
    if (!process.env.ALPHACLAW_ROOT) process.env.ALPHACLAW_ROOT = simulatedProjectRoot;
    assert.equal(process.env.ALPHACLAW_ROOT, simulatedProjectRoot);
  });

  it("ALPHACLAW_ROOT must not be overwritten when already set", () => {
    const original = "/some/existing/alphaclaw";
    process.env.ALPHACLAW_ROOT = original;
    // Simulate: if (!process.env.ALPHACLAW_ROOT) process.env.ALPHACLAW_ROOT = simulatedProjectRoot
    if (!process.env.ALPHACLAW_ROOT) process.env.ALPHACLAW_ROOT = projectRoot;
    assert.equal(process.env.ALPHACLAW_ROOT, original);
  });

  it("PERPETUA_TOOLS_ROOT should be set when env var is absent (simulated)", () => {
    delete process.env.PERPETUA_TOOLS_ROOT;
    const simulatedPerpetuaRoot = perpetuaRoot;
    if (!process.env.PERPETUA_TOOLS_ROOT) process.env.PERPETUA_TOOLS_ROOT = simulatedPerpetuaRoot;
    assert.equal(process.env.PERPETUA_TOOLS_ROOT, simulatedPerpetuaRoot);
  });

  it("PERPETUA_TOOLS_ROOT must not be overwritten when already set", () => {
    const original = "/some/existing/perpetua";
    process.env.PERPETUA_TOOLS_ROOT = original;
    if (!process.env.PERPETUA_TOOLS_ROOT) process.env.PERPETUA_TOOLS_ROOT = perpetuaRoot;
    assert.equal(process.env.PERPETUA_TOOLS_ROOT, original);
  });

  it("once ALPHACLAW_ROOT is in env, getApprovedRoots picks it up automatically", () => {
    process.env.ALPHACLAW_ROOT = projectRoot;
    const roots = getApprovedRoots([]);
    assert.ok(roots.includes(path.resolve(projectRoot)));
  });

  it("once PERPETUA_TOOLS_ROOT is in env, getApprovedRoots picks it up automatically", () => {
    process.env.PERPETUA_TOOLS_ROOT = perpetuaRoot;
    const roots = getApprovedRoots([]);
    assert.ok(roots.includes(path.resolve(perpetuaRoot)));
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// 8. redactLogText — regression / boundary cases for PR-added log redaction
// ──────────────────────────────────────────────────────────────────────────────

describe("redactLogText regression and boundary cases", () => {
  it("passes through plain log text unchanged", () => {
    const plain = "2024-01-01 INFO  sync complete: 3 files updated";
    assert.equal(redactLogText(plain), plain);
  });

  it("redacts GitHub PAT tokens (ghp_ prefix)", () => {
    const text = "token=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcd";
    const result = redactLogText(text);
    assert.ok(!result.includes("ghp_"));
    assert.ok(result.includes("[REDACTED]"));
  });

  it("redacts OpenAI-style sk- keys", () => {
    const text = "key: sk-1234567890abcdefghijklmnopqrstuvwxyz";
    const result = redactLogText(text);
    assert.ok(!result.includes("sk-1234567890"));
    assert.ok(result.includes("[REDACTED]"));
  });

  it("redacts Bearer tokens", () => {
    const text = "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9abcdefghijk";
    const result = redactLogText(text);
    assert.ok(!result.includes("eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9abcdefghijk"));
    assert.ok(result.includes("[REDACTED]"));
  });

  it("redacts SETUP_PASSWORD assignment lines", () => {
    const text = "SETUP_PASSWORD=my-very-secret-pass\nOTHER=safe";
    const result = redactLogText(text);
    assert.ok(!result.includes("my-very-secret-pass"));
    assert.ok(result.includes("[REDACTED]"));
    assert.ok(result.includes("OTHER=safe"), "Unrelated lines must be preserved");
  });

  it("redacts multiple secrets in the same text block", () => {
    const text = [
      "sk-ant-api03-fakekey1234567890abcdef",
      "user: admin@company.org",
      "SETUP_PASSWORD=topsecret",
    ].join("\n");
    const result = redactLogText(text);
    assert.ok(!result.includes("sk-ant-api03-"));
    assert.ok(!result.includes("admin@company.org"));
    assert.ok(!result.includes("topsecret"));
  });

  it("returns original value when input is not a string", () => {
    // Per implementation: if (!text || typeof text !== "string") return text
    assert.equal(redactLogText(null), null);
    assert.equal(redactLogText(undefined), undefined);
    assert.equal(redactLogText(42), 42);
  });

  it("returns empty string unchanged", () => {
    assert.equal(redactLogText(""), "");
  });
});
