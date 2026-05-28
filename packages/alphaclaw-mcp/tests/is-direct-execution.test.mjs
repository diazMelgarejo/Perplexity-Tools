/**
 * Entry-point detection for alphaclaw-mcp (no full server import).
 *
 * Run: node --test packages/alphaclaw-mcp/tests/is-direct-execution.test.mjs
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { isDirectExecution } from "../build/is-direct-execution.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const indexAbs = path.resolve(__dirname, "../build/index.js");
const indexRel = path.relative(process.cwd(), indexAbs);
const indexUrl = pathToFileURL(indexAbs).href;

describe("isDirectExecution", () => {
  it("returns false when entryArgv is missing", () => {
    assert.equal(isDirectExecution(indexUrl), false);
  });

  it("returns true when argv resolves to this module (absolute path)", () => {
    assert.equal(isDirectExecution(indexUrl, indexAbs), true);
  });

  it("returns true when argv is a relative path to this module", () => {
    assert.equal(isDirectExecution(indexUrl, indexRel), true);
  });

  it("rejects the broken file:// string prefix comparison for relative argv", () => {
    const brokenMainCheck = indexUrl === `file://${indexRel}`;
    assert.equal(
      brokenMainCheck,
      false,
      "relative argv must not match import.meta.url via string concat"
    );
    assert.equal(isDirectExecution(indexUrl, indexRel), true);
  });

  it("returns false for unrelated entry paths", () => {
    assert.equal(isDirectExecution(indexUrl, path.join(os.tmpdir(), "other.js")), false);
  });

  it("returns false for empty string entryArgv", () => {
    // path.resolve("") resolves to cwd, not the module path
    assert.equal(isDirectExecution(indexUrl, ""), false);
  });

  it("returns false for null entryArgv", () => {
    assert.equal(isDirectExecution(indexUrl, null), false);
  });

  it("returns false when importMetaUrl differs only in extension", () => {
    const tsUrl = indexUrl.replace(/\.js$/, ".ts");
    assert.equal(isDirectExecution(tsUrl, indexAbs), false);
  });
});
