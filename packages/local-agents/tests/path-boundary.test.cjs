/**
 * Security fix 4 — MCP path boundary tests (node --test, no vitest required).
 * Run: node --test packages/local-agents/tests/path-boundary.test.js
 */

"use strict";

const { describe, it, before, after } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const path = require("path");

const {
  getApprovedRoots,
  resolveAllowedPath,
  redactLogText,
} = require("../src/path-boundary.cjs");

const REDACTED = "[REDACTED]";

describe("path-boundary", () => {
  let tmp;
  let sandboxRoot;
  let outsideFile;

  before(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), "mcp-path-"));
    sandboxRoot = path.join(tmp, "sandbox");
    fs.mkdirSync(sandboxRoot, { recursive: true });
    fs.writeFileSync(path.join(sandboxRoot, "inside.txt"), "hello");
    outsideFile = path.join(tmp, "outside.txt");
    fs.writeFileSync(outsideFile, "secret-outside");
  });

  after(() => {
    fs.rmSync(tmp, { recursive: true, force: true });
  });

  it("allows relative paths under an approved root", () => {
    const roots = [sandboxRoot];
    const res = resolveAllowedPath("inside.txt", { roots, baseForRelative: sandboxRoot });
    assert.equal(res.ok, true);
    assert.equal(res.abs, fs.realpathSync(path.join(sandboxRoot, "inside.txt")));
  });

  it("allows absolute paths when under an approved root", () => {
    const inside = path.join(sandboxRoot, "inside.txt");
    const res = resolveAllowedPath(inside, { roots: [sandboxRoot] });
    assert.equal(res.ok, true);
    assert.equal(res.abs, fs.realpathSync(inside));
  });

  it("rejects absolute paths outside approved roots", () => {
    const res = resolveAllowedPath(outsideFile, { roots: [sandboxRoot] });
    assert.equal(res.ok, false);
    assert.match(res.error, /outside approved MCP roots/i);
    assert.equal(res.rejectedOutsideRoots, true);
  });

  it("rejects symlink escapes", () => {
    if (process.platform === "win32") return;
    const link = path.join(sandboxRoot, "escape-link");
    try {
      fs.symlinkSync(outsideFile, link);
    } catch {
      return;
    }
    const res = resolveAllowedPath(link, { roots: [sandboxRoot] });
    assert.equal(res.ok, false);
    assert.match(res.error, /symlink|escapes|outside approved MCP roots/i);
  });

  it("redacts secrets and env assignments in log text", () => {
    const raw =
      "token=abc\nSETUP_PASSWORD=hunter2\nContact user@example.com\nAIzaSyDUMMYKEY123456789012345678901";
    const redacted = redactLogText(raw);
    assert.ok(!redacted.includes("hunter2"));
    assert.ok(!redacted.includes("user@example.com"));
    assert.ok(!redacted.includes("AIzaSyDUMMY"));
    assert.ok(redacted.includes(REDACTED));
  });
});

describe("getApprovedRoots", () => {
  it("parses MCP_APPROVED_ROOTS delimiter list", () => {
    const a = path.join(os.tmpdir(), "mcp-root-a");
    const b = path.join(os.tmpdir(), "mcp-root-b");
    const prev = process.env.MCP_APPROVED_ROOTS;
    process.env.MCP_APPROVED_ROOTS = `${a}${path.delimiter}${b}`;
    try {
      const roots = getApprovedRoots();
      assert.ok(roots.includes(a));
      assert.ok(roots.includes(b));
    } finally {
      if (prev === undefined) delete process.env.MCP_APPROVED_ROOTS;
      else process.env.MCP_APPROVED_ROOTS = prev;
    }
  });
});
