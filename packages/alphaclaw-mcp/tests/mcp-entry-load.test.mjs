/**
 * Smoke test: alphaclaw-mcp build output must load without ESM/CJS interop errors.
 * Catches regressions like local-agents "type":"module" with CommonJS .js sources.
 *
 * Run: node --test packages/alphaclaw-mcp/tests/mcp-entry-load.test.mjs
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

describe("alphaclaw-mcp entry load", () => {
  it("imports build/index.js without throwing (orchestrator CJS interop)", async () => {
    const indexPath = path.resolve(__dirname, "../build/index.js");
    const mod = await import(pathToFileURL(indexPath).href);
    assert.equal(typeof mod.startServer, "function");
    assert.equal(typeof mod.isDirectExecution, "function");
    assert.equal(typeof mod.evaluatePathGate, "function");
  });
});
