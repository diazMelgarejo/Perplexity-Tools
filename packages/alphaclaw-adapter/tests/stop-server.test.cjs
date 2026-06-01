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

describe("startServer — pidFile destructuring fix", () => {
  let tmpDir;
  let pidFile;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "ac-start-"));
    pidFile = path.join(tmpDir, "alphaclaw-server.pid");
  });

  afterEach(() => {
    try {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    } catch {
      /* ignore */
    }
  });

  it("startServer uses defaultPidFile(alphaclawRoot) when no pidFile arg given", async () => {
    const adapterPath = require.resolve("../src/index.js");
    const origSpawn = cp.spawn;
    cp.spawn = () => ({ pid: 111111, unref() {} });
    delete require.cache[adapterPath];
    const fresh = require("../src/index.js");
    fresh.health = async () => ({ ok: false });
    try {
      const result = await fresh.startServer({ alphaclawRoot: tmpDir, port: 39998 });
      assert.equal(result.ok, true);
      assert.equal(result.pid, 111111);
      // pidFile must be the default: <alphaclawRoot>/alphaclaw-server.pid
      const expectedPidFile = path.join(tmpDir, "alphaclaw-server.pid");
      assert.equal(result.pidFile, expectedPidFile);
      assert.equal(fs.readFileSync(expectedPidFile, "utf8"), "111111");
    } finally {
      cp.spawn = origSpawn;
      delete require.cache[adapterPath];
      require("../src/index.js");
    }
  });

  it("startServer with no port arg still returns a numeric port in result", async () => {
    // Verifies that the refactored pidFile destructuring did not break the port fallback path.
    const adapterPath = require.resolve("../src/index.js");
    const origSpawn = cp.spawn;
    cp.spawn = () => ({ pid: 99999, unref() {} });
    delete require.cache[adapterPath];
    const fresh = require("../src/index.js");
    fresh.health = async () => ({ ok: false });
    try {
      const result = await fresh.startServer({ pidFile, alphaclawRoot: tmpDir });
      // ok or error — either way port must be a positive integer
      assert.equal(typeof result.port, "number");
      assert.ok(result.port > 0, "port should be positive");
    } finally {
      cp.spawn = origSpawn;
      delete require.cache[adapterPath];
      require("../src/index.js");
    }
  });

  it("startServer returns ok:false with error when spawn throws", async () => {
    const adapterPath = require.resolve("../src/index.js");
    const origSpawn = cp.spawn;
    cp.spawn = () => { throw new Error("spawn ENOENT"); };
    delete require.cache[adapterPath];
    const fresh = require("../src/index.js");
    fresh.health = async () => ({ ok: false });
    try {
      const result = await fresh.startServer({ pidFile, alphaclawRoot: tmpDir, port: 39996 });
      assert.equal(result.ok, false);
      assert.equal(typeof result.error, "string");
      assert.match(result.error, /spawn ENOENT/);
      assert.equal(result.port, 39996);
      assert.equal(fs.existsSync(pidFile), false, "no pid file on spawn failure");
    } finally {
      cp.spawn = origSpawn;
      delete require.cache[adapterPath];
      require("../src/index.js");
    }
  });

  it("startServer returns port in result for both success and already-running paths", async () => {
    const adapterPath = require.resolve("../src/index.js");
    const origSpawn = cp.spawn;
    cp.spawn = () => ({ pid: 222222, unref() {} });
    delete require.cache[adapterPath];
    const fresh = require("../src/index.js");

    // already-running path
    fresh.health = async () => ({ ok: true });
    const alreadyResult = await fresh.startServer({ pidFile, alphaclawRoot: tmpDir, port: 39995 });
    assert.equal(alreadyResult.port, 39995);

    // spawn path
    fresh.health = async () => ({ ok: false });
    const spawnResult = await fresh.startServer({ pidFile, alphaclawRoot: tmpDir, port: 39994 });
    assert.equal(spawnResult.port, 39994);

    cp.spawn = origSpawn;
    delete require.cache[adapterPath];
    require("../src/index.js");
  });

  it("startServer pidFile arg takes precedence over defaultPidFile (regression)", async () => {
    const adapterPath = require.resolve("../src/index.js");
    const origSpawn = cp.spawn;
    cp.spawn = () => ({ pid: 333333, unref() {} });
    delete require.cache[adapterPath];
    const fresh = require("../src/index.js");
    fresh.health = async () => ({ ok: false });
    const customPidFile = path.join(tmpDir, "custom.pid");
    try {
      const result = await fresh.startServer({
        pidFile: customPidFile,
        alphaclawRoot: tmpDir,
        port: 39993,
      });
      assert.equal(result.ok, true);
      assert.equal(result.pidFile, customPidFile);
      // default path must NOT be written
      const defaultPath = path.join(tmpDir, "alphaclaw-server.pid");
      assert.equal(fs.existsSync(defaultPath), false, "default pidFile must not be written when custom pidFile is specified");
      assert.equal(fs.readFileSync(customPidFile, "utf8"), "333333");
    } finally {
      cp.spawn = origSpawn;
      delete require.cache[adapterPath];
      require("../src/index.js");
    }
  });
});
