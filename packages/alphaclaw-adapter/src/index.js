/**
 * packages/alphaclaw-adapter/src/index.js
 *
 * Perpetua-Tools — AlphaClaw Adapter (Gate 1 stub)
 *
 * Exports typed wrappers around AlphaClaw's CLI and HTTP surface.
 * All interaction is via spawned processes or HTTP — never via require().
 *
 * Current state: Gate 0 scaffold. HTTP client and CLI wrapper
 * will be implemented as Gate 1 work (see system-design §8).
 */

"use strict";

const { spawnSync } = require("child_process");
const http = require("http");
const path = require("path");

const DEFAULT_PORT = parseInt(process.env.ALPHACLAW_PORT || "3000", 10);
const DEFAULT_HOST = process.env.ALPHACLAW_HOST || "127.0.0.1";
const ALPHACLAW_ROOT = process.env.ALPHACLAW_ROOT
  || path.resolve(__dirname, "..", "..", "..", "..", "..", "AlphaClaw");

// ─── HTTP helpers ─────────────────────────────────────────────────────────────

function httpGet(path_, timeout = 5000) {
  return new Promise((resolve, reject) => {
    const req = http.get(
      { host: DEFAULT_HOST, port: DEFAULT_PORT, path: path_, timeout },
      (res) => {
        let data = "";
        res.on("data", (c) => (data += c));
        res.on("end", () => {
          try { resolve({ status: res.statusCode, body: JSON.parse(data) }); }
          catch { resolve({ status: res.statusCode, body: data }); }
        });
      }
    );
    req.on("error", reject);
    req.on("timeout", () => { req.destroy(); reject(new Error("timeout")); });
  });
}

// ─── AlphaClaw control API ────────────────────────────────────────────────────

/** Liveness probe — no auth required */
async function health() {
  try {
    const r = await httpGet("/health");
    return { ok: r.status === 200, status: r.status, body: r.body };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

/** Gate 1 TODO: full adapter methods:
 *  status(), gatewayStatus(), gatewayDashboard(), restartGateway(),
 *  login(password), getModelsConfig(), putModelsConfig(config), tailLogs(n)
 */

// ─── AlphaClaw CLI control ────────────────────────────────────────────────────

/** Start AlphaClaw server. Returns { ok, pid, port } or { ok:false, error } */
function startServer({ port = DEFAULT_PORT } = {}) {
  const env = { ...process.env, PORT: String(port) };
  const result = spawnSync(
    "node",
    ["bin/alphaclaw.js", "start"],
    { cwd: ALPHACLAW_ROOT, env, detached: true, stdio: "ignore" }
  );
  if (result.error) return { ok: false, error: result.error.message };
  return { ok: true, port };
}

module.exports = { health, startServer, DEFAULT_PORT, DEFAULT_HOST, ALPHACLAW_ROOT };
