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

// ─── Additional tests: configure(_port) state persistence ────────────────────
//
// These tests verify that the configure({ port: p }) call inside startServer()
// actually persists module _port so that all subsequent adapter calls (health,
// waitForReady, etc.) use the correct port without the caller needing to call
// configure() again.

describe("configure _port alignment: state persistence and override", () => {
  // Use a port range well away from the suite above and from stop-server tests.
  const ALIGN_PORT_A = 40200; // commandeer; _port persistence check
  const ALIGN_PORT_B = 40201; // falsy-port fallback preserves pre-configured _port
  const ALIGN_PORT_C_STALE = 40202; // pre-configured stale port (should NOT be probed)
  const ALIGN_PORT_C_REAL = 40203; // explicit override port (should be probed)
  const ALIGN_PORT_D = 40204; // regression trap: pre-config != explicit, only explicit has listener
  const ALIGN_PORT_E = 40205; // spawn path port alignment

  let tmpDir;
  let pidFile;
  let activeServers;

  async function spawnHealthServer(port) {
    const srv = await listenHealthServer(port);
    activeServers.push(srv);
    return srv;
  }

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "ac-align-"));
    pidFile = path.join(tmpDir, "alphaclaw-server.pid");
    activeServers = [];
  });

  afterEach(async () => {
    for (const srv of activeServers) {
      await closeServer(srv);
    }
    activeServers = [];
    try {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    } catch {
      /* ignore */
    }
  });

  it("after commandeer path _port is set to explicit port so direct health() call succeeds", async () => {
    // After startServer() commandeers on an explicit port, the module _port must
    // remain set to that port. A subsequent health() call must succeed because it
    // probes the same (still-listening) explicit port.
    await spawnHealthServer(ALIGN_PORT_A);
    const fresh = loadFreshAdapter();
    // Fresh module starts with DEFAULT_PORT (3000); no listener on 3000 in this suite.

    try {
      const result = await fresh.startServer({
        alphaclawRoot: tmpDir,
        port: ALIGN_PORT_A,
        pidFile,
      });
      assert.equal(result.ok, true);
      assert.equal(result.already, true);
      assert.equal(result.port, ALIGN_PORT_A);

      // Direct health() call after startServer — must use ALIGN_PORT_A, not 3000.
      const h = await fresh.health();
      assert.equal(h.ok, true, "health() after commandeer must probe the aligned explicit port");
    } finally {
      delete require.cache[require.resolve("../src/index.js")];
    }
  });

  it("startServer without explicit port preserves the current module _port via configure", async () => {
    // When no port is passed to startServer, p = port || _port = _port.
    // configure({ port: _port }) is effectively a no-op — _port stays the same.
    // Verify the returned port matches the pre-configured _port.
    const fresh = loadFreshAdapter();
    fresh.configure({ port: ALIGN_PORT_B });

    const origSpawn = cp.spawn;
    cp.spawn = () => ({ pid: 811111, unref() {} });

    try {
      // Nothing listens on ALIGN_PORT_B, so health() → ok:false → spawn path.
      const result = await fresh.startServer({
        alphaclawRoot: tmpDir,
        pidFile,
        // no port param
      });
      assert.equal(result.ok, true);
      assert.equal(result.pid, 811111);
      assert.equal(result.port, ALIGN_PORT_B,
        "returned port must match the pre-configured _port when no explicit port given");
      assert.equal(result.already, undefined);
    } finally {
      cp.spawn = origSpawn;
      delete require.cache[require.resolve("../src/index.js")];
    }
  });

  it("explicit port overrides a pre-configured _port before the health probe (regression trap)", async () => {
    // REGRESSION TRAP: Without the configure({ port: p }) fix, health() would probe
    // the stale pre-configured port (ALIGN_PORT_C_STALE) instead of the explicit
    // ALIGN_PORT_C_REAL. The test would then fail to commandeer even though a server
    // is running on ALIGN_PORT_C_REAL and instead would incorrectly spawn.
    await spawnHealthServer(ALIGN_PORT_C_REAL);
    const fresh = loadFreshAdapter();
    fresh.configure({ port: ALIGN_PORT_C_STALE }); // stale — nothing listening here

    const origSpawn = cp.spawn;
    let spawnCalled = false;
    cp.spawn = () => {
      spawnCalled = true;
      return { pid: 822222, unref() {} };
    };

    try {
      const result = await fresh.startServer({
        alphaclawRoot: tmpDir,
        port: ALIGN_PORT_C_REAL, // explicit override
        pidFile,
      });
      assert.equal(result.ok, true);
      assert.equal(result.already, true,
        "must commandeer: configure() before health() must probe the explicit port");
      assert.equal(result.port, ALIGN_PORT_C_REAL);
      assert.equal(spawnCalled, false,
        "spawn must not be called when explicit port has a running server");
    } finally {
      cp.spawn = origSpawn;
      delete require.cache[require.resolve("../src/index.js")];
    }
  });

  it("health probe only targets the explicit port, not a previously configured stale port", async () => {
    // Complementary to the regression trap above: verify that the stale pre-configured
    // port is never contacted by checking that a server that ONLY runs on ALIGN_PORT_D
    // is commandeered when startServer is called with port: ALIGN_PORT_D, regardless of
    // what _port was set to before.
    await spawnHealthServer(ALIGN_PORT_D);
    const fresh = loadFreshAdapter();
    // Pre-configure to a completely different port with no listener.
    fresh.configure({ port: ALIGN_PORT_C_STALE });

    const origSpawn = cp.spawn;
    let spawnCalled = false;
    cp.spawn = () => {
      spawnCalled = true;
      return { pid: 833333, unref() {} };
    };

    try {
      const result = await fresh.startServer({
        alphaclawRoot: tmpDir,
        port: ALIGN_PORT_D,
        pidFile,
      });
      // With configure({ port: p }) in place, health() targets ALIGN_PORT_D → ok.
      assert.equal(result.ok, true);
      assert.equal(result.already, true);
      assert.equal(result.port, ALIGN_PORT_D);
      assert.equal(spawnCalled, false);
    } finally {
      cp.spawn = origSpawn;
      delete require.cache[require.resolve("../src/index.js")];
    }
  });

  it("on spawn path configure aligns _port so waitForReady does not poll wrong port", async () => {
    // Even when health() returns ok:false (no server yet), configure({ port: p })
    // was already called. A subsequent waitForReady() must therefore poll the explicit
    // port rather than any previously set _port.
    const fresh = loadFreshAdapter();
    // Pre-configure to a stale port — nothing ever listens there.
    fresh.configure({ port: ALIGN_PORT_C_STALE });

    const origSpawn = cp.spawn;
    cp.spawn = () => ({ pid: 844444, unref() {} });

    // Bring up the explicit port 400 ms after startServer returns.
    let explicitSrv = null;
    const laterListen = new Promise((resolve, reject) => {
      setTimeout(async () => {
        try {
          explicitSrv = await spawnHealthServer(ALIGN_PORT_E);
          resolve();
        } catch (e) {
          reject(e);
        }
      }, 400);
    });

    try {
      const started = await fresh.startServer({
        alphaclawRoot: tmpDir,
        port: ALIGN_PORT_E,
        pidFile,
      });
      assert.equal(started.ok, true);
      assert.equal(started.already, undefined, "must not commandeer — nothing on ALIGN_PORT_E yet");
      assert.equal(started.port, ALIGN_PORT_E);

      await laterListen;

      // waitForReady must poll ALIGN_PORT_E (aligned by configure), not ALIGN_PORT_C_STALE.
      const ready = await fresh.waitForReady({ timeoutMs: 5000, intervalMs: 100 });
      assert.equal(ready.ready, true,
        "waitForReady must succeed by polling the aligned explicit port");
    } finally {
      cp.spawn = origSpawn;
      delete require.cache[require.resolve("../src/index.js")];
    }
  });
});
