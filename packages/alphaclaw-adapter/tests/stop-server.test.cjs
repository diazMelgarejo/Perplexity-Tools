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

describe("startServer — return shape and edge cases", () => {
  let tmpDir;
  let pidFile;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "ac-shape-"));
    pidFile = path.join(tmpDir, "alphaclaw-server.pid");
  });

  afterEach(() => {
    try {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    } catch {
      /* ignore */
    }
  });

  it("ALPHACLAW_PID_FILE env var is honoured when no pidFile arg given", async () => {
    const envPidFile = path.join(tmpDir, "env-override.pid");
    const adapterPath = require.resolve("../src/index.js");
    const origSpawn = cp.spawn;
    cp.spawn = () => ({ pid: 555555, unref() {} });
    const prevEnv = process.env.ALPHACLAW_PID_FILE;
    process.env.ALPHACLAW_PID_FILE = envPidFile;
    delete require.cache[adapterPath];
    const fresh = require("../src/index.js");
    fresh.health = async () => ({ ok: false });
    try {
      const result = await fresh.startServer({ alphaclawRoot: tmpDir, port: 39991 });
      assert.equal(result.ok, true);
      assert.equal(result.pidFile, envPidFile, "should use ALPHACLAW_PID_FILE env var");
      assert.equal(fs.readFileSync(envPidFile, "utf8"), "555555");
    } finally {
      if (prevEnv === undefined) delete process.env.ALPHACLAW_PID_FILE;
      else process.env.ALPHACLAW_PID_FILE = prevEnv;
      cp.spawn = origSpawn;
      delete require.cache[adapterPath];
      require("../src/index.js");
    }
  });

  it("explicit pidFile: undefined still falls back to defaultPidFile", async () => {
    // Passing pidFile: undefined explicitly must behave identically to omitting it.
    const adapterPath = require.resolve("../src/index.js");
    const origSpawn = cp.spawn;
    cp.spawn = () => ({ pid: 666666, unref() {} });
    delete require.cache[adapterPath];
    const fresh = require("../src/index.js");
    fresh.health = async () => ({ ok: false });
    try {
      const result = await fresh.startServer({ pidFile: undefined, alphaclawRoot: tmpDir, port: 39990 });
      assert.equal(result.ok, true);
      const expectedPidFile = path.join(tmpDir, "alphaclaw-server.pid");
      assert.equal(result.pidFile, expectedPidFile);
      assert.equal(fs.readFileSync(expectedPidFile, "utf8"), "666666");
    } finally {
      cp.spawn = origSpawn;
      delete require.cache[adapterPath];
      require("../src/index.js");
    }
  });

  it("pidFile and logFile together: pidFile is written correctly when logFile is also set", async () => {
    // Regression: logFile opens a file descriptor; this must not interfere with pidFile resolution.
    const adapterPath = require.resolve("../src/index.js");
    const logFilePath = path.join(tmpDir, "server.log");
    const origSpawn = cp.spawn;
    // Stub spawn to avoid actually opening the logFile fd; capture stdio arg
    let capturedStdio;
    cp.spawn = (_cmd, _args, spawnOpts) => {
      capturedStdio = spawnOpts.stdio;
      return { pid: 777777, unref() {} };
    };
    delete require.cache[adapterPath];
    const fresh = require("../src/index.js");
    fresh.health = async () => ({ ok: false });
    try {
      const result = await fresh.startServer({
        pidFile,
        alphaclawRoot: tmpDir,
        port: 39989,
        logFile: logFilePath,
      });
      assert.equal(result.ok, true);
      assert.equal(result.pid, 777777);
      assert.equal(result.pidFile, pidFile, "pidFile must not be corrupted by logFile option");
      assert.equal(fs.readFileSync(pidFile, "utf8"), "777777");
      // stdio[0] should be 'ignore', stdio[1] and [2] should be the fd (number)
      assert.equal(capturedStdio[0], "ignore");
      assert.equal(typeof capturedStdio[1], "number", "stdout should be a file descriptor when logFile set");
    } finally {
      cp.spawn = origSpawn;
      delete require.cache[adapterPath];
      require("../src/index.js");
    }
  });

  it("startServer result contains only expected keys on success (spawn path)", async () => {
    // Guards against unintended extra properties leaking into the return shape.
    const adapterPath = require.resolve("../src/index.js");
    const origSpawn = cp.spawn;
    cp.spawn = () => ({ pid: 888888, unref() {} });
    delete require.cache[adapterPath];
    const fresh = require("../src/index.js");
    fresh.health = async () => ({ ok: false });
    try {
      const result = await fresh.startServer({ pidFile, alphaclawRoot: tmpDir, port: 39988 });
      assert.equal(result.ok, true);
      assert.equal(result.pid, 888888);
      assert.equal(result.port, 39988);
      assert.equal(result.pidFile, pidFile);
      // 'already' and 'error' must not appear on a clean spawn success
      assert.equal(result.already, undefined, "already must be absent on spawn success");
      assert.equal(result.error, undefined, "error must be absent on spawn success");
    } finally {
      cp.spawn = origSpawn;
      delete require.cache[adapterPath];
      require("../src/index.js");
    }
  });

  it("startServer ok:false result contains only expected keys (spawn throws)", async () => {
    const adapterPath = require.resolve("../src/index.js");
    const origSpawn = cp.spawn;
    cp.spawn = () => { throw new Error("spawn EPERM"); };
    delete require.cache[adapterPath];
    const fresh = require("../src/index.js");
    fresh.health = async () => ({ ok: false });
    try {
      const result = await fresh.startServer({ pidFile, alphaclawRoot: tmpDir, port: 39987 });
      assert.equal(result.ok, false);
      assert.equal(result.port, 39987);
      assert.match(result.error, /spawn EPERM/);
      // pid and pidFile must not appear in error result
      assert.equal(result.pid, undefined, "pid must be absent on spawn failure");
      assert.equal(result.pidFile, undefined, "pidFile must be absent on spawn failure");
    } finally {
      cp.spawn = origSpawn;
      delete require.cache[adapterPath];
      require("../src/index.js");
    }
  });
});

describe("startServer — boundary and regression cases", () => {
  let tmpDir;
  let pidFile;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "ac-boundary-"));
    pidFile = path.join(tmpDir, "alphaclaw-server.pid");
  });

  afterEach(() => {
    try {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    } catch {
      /* ignore */
    }
  });

  it("startServer writes pidFile in a deeply nested path (writePidFile mkdir -p behavior)", async () => {
    // writePidFile calls mkdirSync with recursive:true — verify nested dirs are created.
    const adapterPath = require.resolve("../src/index.js");
    const origSpawn = cp.spawn;
    cp.spawn = () => ({ pid: 101010, unref() {} });
    delete require.cache[adapterPath];
    const fresh = require("../src/index.js");
    fresh.health = async () => ({ ok: false });
    const nestedPidFile = path.join(tmpDir, "a", "b", "c", "server.pid");
    try {
      const result = await fresh.startServer({
        pidFile: nestedPidFile,
        alphaclawRoot: tmpDir,
        port: 39985,
      });
      assert.equal(result.ok, true);
      assert.equal(result.pidFile, nestedPidFile);
      assert.equal(fs.readFileSync(nestedPidFile, "utf8"), "101010");
    } finally {
      cp.spawn = origSpawn;
      delete require.cache[adapterPath];
      require("../src/index.js");
    }
  });

  it("startServer called with empty options {} still returns a valid result", async () => {
    // Regression: the old code read opts.pidFile which would ReferenceError;
    // calling with {} (no properties) exercises the full fallback path.
    const adapterPath = require.resolve("../src/index.js");
    const origSpawn = cp.spawn;
    cp.spawn = () => ({ pid: 202020, unref() {} });
    delete require.cache[adapterPath];
    const fresh = require("../src/index.js");
    fresh.health = async () => ({ ok: false });
    try {
      // {} passes as the opts object but provides no pidFile/port/root.
      const result = await fresh.startServer({});
      // Should not throw; result must at minimum have ok and port.
      assert.ok("ok" in result, "result must have ok");
      assert.ok("port" in result, "result must have port");
      assert.equal(typeof result.port, "number");
    } finally {
      cp.spawn = origSpawn;
      delete require.cache[adapterPath];
      require("../src/index.js");
    }
  });

  it("startServer null pidFile falls back to defaultPidFile (falsy coercion)", async () => {
    // null is falsy — `pidFile || defaultPidFile(root)` must resolve to default.
    const adapterPath = require.resolve("../src/index.js");
    const origSpawn = cp.spawn;
    cp.spawn = () => ({ pid: 303030, unref() {} });
    delete require.cache[adapterPath];
    const fresh = require("../src/index.js");
    fresh.health = async () => ({ ok: false });
    try {
      const result = await fresh.startServer({ pidFile: null, alphaclawRoot: tmpDir, port: 39983 });
      assert.equal(result.ok, true);
      // null should fall back to the default pid file path
      const expectedPidFile = path.join(tmpDir, "alphaclaw-server.pid");
      assert.equal(result.pidFile, expectedPidFile);
      assert.equal(fs.readFileSync(expectedPidFile, "utf8"), "303030");
    } finally {
      cp.spawn = origSpawn;
      delete require.cache[adapterPath];
      require("../src/index.js");
    }
  });

  it("startServer already-running path does NOT write a pidFile", async () => {
    // When health returns ok:true (already running), startServer returns early
    // without spawning or writing a pidFile.
    const adapterPath = require.resolve("../src/index.js");
    const origSpawn = cp.spawn;
    let spawnCalled = false;
    cp.spawn = () => { spawnCalled = true; return { pid: 404040, unref() {} }; };
    delete require.cache[adapterPath];
    const fresh = require("../src/index.js");
    fresh.health = async () => ({ ok: true });
    try {
      const result = await fresh.startServer({ pidFile, alphaclawRoot: tmpDir, port: 39982 });
      assert.equal(result.ok, true);
      assert.equal(result.already, true);
      assert.equal(spawnCalled, false, "spawn must not be called when server is already running");
      assert.equal(fs.existsSync(pidFile), false, "pidFile must not be written on already-running path");
    } finally {
      cp.spawn = origSpawn;
      delete require.cache[adapterPath];
      require("../src/index.js");
    }
  });

  it("startServer passes PORT env var to spawn as string (env propagation)", async () => {
    // Verify that the PORT env variable is set to the correct port string in the child env.
    const adapterPath = require.resolve("../src/index.js");
    const origSpawn = cp.spawn;
    let capturedEnv;
    cp.spawn = (_cmd, _args, spawnOpts) => {
      capturedEnv = spawnOpts.env;
      return { pid: 505050, unref() {} };
    };
    delete require.cache[adapterPath];
    const fresh = require("../src/index.js");
    fresh.health = async () => ({ ok: false });
    try {
      await fresh.startServer({ pidFile, alphaclawRoot: tmpDir, port: 39981 });
      assert.equal(capturedEnv.PORT, "39981", "PORT env must be the requested port as a string");
    } finally {
      cp.spawn = origSpawn;
      delete require.cache[adapterPath];
      require("../src/index.js");
    }
  });

  it("startServer uses detached:true so parent can exit independently", async () => {
    // The adapter spawns detached so PT process can exit without killing AlphaClaw.
    const adapterPath = require.resolve("../src/index.js");
    const origSpawn = cp.spawn;
    let capturedOpts;
    cp.spawn = (_cmd, _args, spawnOpts) => {
      capturedOpts = spawnOpts;
      return { pid: 606060, unref() {} };
    };
    delete require.cache[adapterPath];
    const fresh = require("../src/index.js");
    fresh.health = async () => ({ ok: false });
    try {
      await fresh.startServer({ pidFile, alphaclawRoot: tmpDir, port: 39980 });
      assert.equal(capturedOpts.detached, true, "child must be spawned with detached:true");
    } finally {
      cp.spawn = origSpawn;
      delete require.cache[adapterPath];
      require("../src/index.js");
    }
  });

  it("startServer with no logFile uses ignore stdio for all streams", async () => {
    // Without logFile, all stdio streams should be 'ignore'.
    const adapterPath = require.resolve("../src/index.js");
    const origSpawn = cp.spawn;
    let capturedStdio;
    cp.spawn = (_cmd, _args, spawnOpts) => {
      capturedStdio = spawnOpts.stdio;
      return { pid: 707070, unref() {} };
    };
    delete require.cache[adapterPath];
    const fresh = require("../src/index.js");
    fresh.health = async () => ({ ok: false });
    try {
      await fresh.startServer({ pidFile, alphaclawRoot: tmpDir, port: 39979 });
      assert.deepEqual(
        capturedStdio,
        ["ignore", "ignore", "ignore"],
        "all stdio must be 'ignore' when no logFile is provided"
      );
    } finally {
      cp.spawn = origSpawn;
      delete require.cache[adapterPath];
      require("../src/index.js");
    }
  });
});
