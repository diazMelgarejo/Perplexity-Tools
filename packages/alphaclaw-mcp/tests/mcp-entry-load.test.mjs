/**
 * Smoke test: alphaclaw-mcp build output must load without ESM/CJS interop errors.
 * Catches regressions like local-agents "type":"module" with CommonJS .js sources.
 *
 * Run: node --test packages/alphaclaw-mcp/tests/mcp-entry-load.test.mjs
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const indexPath = path.resolve(__dirname, "../build/index.js");

describe("alphaclaw-mcp entry load", () => {
  it("imports build/index.js without throwing (orchestrator CJS interop)", async () => {
    const mod = await import(pathToFileURL(indexPath).href);
    assert.equal(typeof mod.startServer, "function");
    assert.equal(typeof mod.isDirectExecution, "function");
    assert.equal(typeof mod.evaluatePathGate, "function");
  });
});

describe("index.js isDirectExecution wrapper", () => {
  it("returns false when given an unrelated absolute path", async () => {
    const { isDirectExecution } = await import(pathToFileURL(indexPath).href);
    const unrelated = path.join(os.tmpdir(), "unrelated-script.js");
    assert.equal(isDirectExecution(unrelated), false);
  });

  it("returns true when given the index.js absolute path", async () => {
    const { isDirectExecution } = await import(pathToFileURL(indexPath).href);
    assert.equal(isDirectExecution(indexPath), true);
  });

  it("returns true when given the index.js relative path", async () => {
    const { isDirectExecution } = await import(pathToFileURL(indexPath).href);
    const relPath = path.relative(process.cwd(), indexPath);
    assert.equal(isDirectExecution(relPath), true);
  });

  it("returns false when called with no arguments", async () => {
    // Default argv is process.argv[1] (test runner path), not index.js
    const { isDirectExecution } = await import(pathToFileURL(indexPath).href);
    // When the test runner is not index.js, the default should return false
    if (process.argv[1] !== indexPath) {
      assert.equal(isDirectExecution(), false);
    }
  });

  it("returns false for null entryArgv", async () => {
    const { isDirectExecution } = await import(pathToFileURL(indexPath).href);
    assert.equal(isDirectExecution(null), false);
  });

  it("returns false for empty string entryArgv", async () => {
    const { isDirectExecution } = await import(pathToFileURL(indexPath).href);
    assert.equal(isDirectExecution(""), false);
  });
});
