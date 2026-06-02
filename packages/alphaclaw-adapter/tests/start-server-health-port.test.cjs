/**
 * Regression: startServer must probe /health on the explicit port param,
 * not stale module _port. Run:
 *   node --test packages/alphaclaw-adapter/tests/start-server-health-port.test.cjs
 */

"use strict";

const { describe, it, beforeEach, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const cp = require("child_process");
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");

function listenHealthServer(port) {
  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      if (req.url === "/health") {
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end('{"ok":true}');
        return;
      }
      res.writeHead(404);
      res.end();
    });
    server.on("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

function closeServer(server) {
  return new Promise((resolve) => {
    if (!server) return resolve();
    server.close(() => resolve());
  });
}

function loadFreshAdapter() {
  const adapterPath = require.resolve("../src/index.js");
  delete require.cache[adapterPath];
  return require("../src/index.js");
}

describe("startServer health probe port alignment", () => {
  let tmpDir;
  let pidFile;
  let defaultPortServer;
  let explicitPortServer;

  const DEFAULT_MODULE_PORT = 3000;
  const EXPLICIT_PORT = 40123;
  const OTHER_PORT = 40124;

  beforeEach(async () => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "ac-health-port-"));
    pidFile = path.join(tmpDir, "alphaclaw-server.pid");
    defaultPortServer = await listenHealthServer(DEFAULT_MODULE_PORT);
  });

  afterEach(async () => {
    await closeServer(defaultPortServer);
    await closeServer(explicitPortServer);
    try {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    } catch {
      /* ignore */
    }
  });

  it("commandeers on explicit port when module _port is still default", async () => {
    explicitPortServer = await listenHealthServer(EXPLICIT_PORT);
    const fresh = loadFreshAdapter();
    assert.equal(fresh.DEFAULT_PORT, DEFAULT_MODULE_PORT);

    let spawnCalled = false;
    const origSpawn = cp.spawn;
    cp.spawn = (...args) => {
      spawnCalled = true;
      return origSpawn(...args);
    };

    try {
      const result = await fresh.startServer({
        alphaclawRoot: tmpDir,
        port: EXPLICIT_PORT,
        pidFile,
      });
      assert.equal(result.ok, true);
      assert.equal(result.already, true);
      assert.equal(result.port, EXPLICIT_PORT);
      assert.equal(spawnCalled, false);
    } finally {
      cp.spawn = origSpawn;
      delete require.cache[require.resolve("../src/index.js")];
    }
  });

  it("does not false-commandeer from default port when explicit port differs", async () => {
    let spawnCalled = false;
    const origSpawn = cp.spawn;
    cp.spawn = (...args) => {
      spawnCalled = true;
      return { pid: 919191, unref() {} };
    };

    const fresh = loadFreshAdapter();

    try {
      const result = await fresh.startServer({
        alphaclawRoot: tmpDir,
        port: OTHER_PORT,
        pidFile,
      });
      assert.equal(result.ok, true);
      assert.equal(result.already, undefined);
      assert.equal(result.pid, 919191);
      assert.equal(result.port, OTHER_PORT);
      assert.equal(spawnCalled, true);
    } finally {
      cp.spawn = origSpawn;
      delete require.cache[require.resolve("../src/index.js")];
    }
  });

  it("waitForReady polls explicit spawn port after startServer", async () => {
    const fresh = loadFreshAdapter();
    const origSpawn = cp.spawn;
    cp.spawn = () => ({ pid: 828282, unref() {} });

    const delayedListen = new Promise((resolve, reject) => {
      setTimeout(async () => {
        try {
          explicitPortServer = await listenHealthServer(EXPLICIT_PORT);
          resolve();
        } catch (err) {
          reject(err);
        }
      }, 300);
    });

    try {
      const started = await fresh.startServer({
        alphaclawRoot: tmpDir,
        port: EXPLICIT_PORT,
        pidFile,
      });
      assert.equal(started.ok, true);
      assert.equal(started.already, undefined);

      await delayedListen;
      const ready = await fresh.waitForReady({
        timeoutMs: 5000,
        intervalMs: 100,
      });
      assert.equal(ready.ready, true);
    } finally {
      cp.spawn = origSpawn;
      delete require.cache[require.resolve("../src/index.js")];
    }
  });
});
