/**
 * Unit tests for PID-file-backed stopServer().
 * Run: node --test packages/alphaclaw-adapter/tests/stop-server.test.cjs
 */

"use strict";

const { describe, it, beforeEach, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
const os = require("os");

const cp = require("child_process");
const adapter = require("../src/index.js");

describe("stopServer PID file", () => {
  let tmpDir;
  let pidFile;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "ac-pid-"));
    pidFile = path.join(tmpDir, "alphaclaw-server.pid");
  });

  afterEach(() => {
    try {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    } catch {
      /* ignore */
    }
  });

  it("defaultPidFile honors ALPHACLAW_PID_FILE", () => {
    const prev = process.env.ALPHACLAW_PID_FILE;
    process.env.ALPHACLAW_PID_FILE = pidFile;
    try {
      assert.equal(adapter.defaultPidFile("/tmp/ac"), pidFile);
    } finally {
      if (prev === undefined) delete process.env.ALPHACLAW_PID_FILE;
      else process.env.ALPHACLAW_PID_FILE = prev;
    }
  });

  it("stopServer returns already when pid file missing and health fails", async () => {
    const origHealth = adapter.health;
    adapter.health = async () => ({ ok: false });
    try {
      const result = await adapter.stopServer({ pidFile });
      assert.equal(result.ok, true);
      assert.equal(result.already, true);
    } finally {
      adapter.health = origHealth;
    }
  });

  it("startServer writes pid file after spawn (no ReferenceError on opts)", async () => {
    const adapterPath = require.resolve("../src/index.js");
    const origSpawn = cp.spawn;
    cp.spawn = () => ({
      pid: 424242,
      unref() {},
    });
    delete require.cache[adapterPath];
    const fresh = require("../src/index.js");
    const origHealth = fresh.health;
    fresh.health = async () => ({ ok: false });
    try {
      const result = await fresh.startServer({
        pidFile,
        alphaclawRoot: tmpDir,
        port: 39999,
      });
      assert.equal(result.ok, true);
      assert.equal(result.pid, 424242);
      assert.equal(result.pidFile, pidFile);
      assert.equal(fs.readFileSync(pidFile, "utf8"), "424242");
    } finally {
      fresh.health = origHealth;
      cp.spawn = origSpawn;
      delete require.cache[adapterPath];
      require("../src/index.js");
    }
  });

  it("stopServer clears stale pid file when process is gone", async () => {
    fs.writeFileSync(pidFile, "999999999", "utf8");
    const origHealth = adapter.health;
    adapter.health = async () => ({ ok: false });
    try {
      const result = await adapter.stopServer({ pidFile });
      assert.equal(result.ok, true);
      assert.equal(result.already, true);
      assert.equal(fs.existsSync(pidFile), false);
    } finally {
      adapter.health = origHealth;
    }
  });
});
