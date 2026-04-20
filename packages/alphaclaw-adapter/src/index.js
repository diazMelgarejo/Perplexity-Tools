/**
 * packages/alphaclaw-adapter/src/index.js
 *
 * Perpetua-Tools — AlphaClaw Adapter  v0.9.9.8
 *
 * Full HTTP+CLI client for AlphaClaw. Drives AlphaClaw exclusively through
 * its CLI and HTTP surface — NEVER via require() of AlphaClaw internals.
 *
 * Architecture: PT is the authoritative control plane for gateway discovery,
 * lifecycle, and routing. This module is the single implementation of that
 * authority. orama-system calls PT; PT calls this.
 *
 * Contract: docs/adapter-interface-contract.md
 * Gate: 1 (implemented 2026-04-20)
 */

"use strict";

const { spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const path = require("path");

// ─── Config constants ─────────────────────────────────────────────────────────

const DEFAULT_PORT = parseInt(process.env.ALPHACLAW_PORT || "3000", 10);
const DEFAULT_HOST = process.env.ALPHACLAW_HOST || "127.0.0.1";
const ALPHACLAW_ROOT =
  process.env.ALPHACLAW_ROOT ||
  path.resolve(__dirname, "..", "..", "..", "..", "..", "AlphaClaw");

/**
 * Candidate ports tried in order by discoverPort().
 * Matches the list used by alphaclaw_bootstrap.py (commandeer-first pattern).
 */
const CANDIDATE_PORTS = [3000, 3001, 18789, 11435, 8080, 4000, 9000];

// ─── Module-level state ───────────────────────────────────────────────────────

/** Session cookie from POST /api/auth/login */
let _cookie = null;

/** Active port — updated by configure() or discoverPort() */
let _port = DEFAULT_PORT;

/** Active host */
let _host = DEFAULT_HOST;

/** PID of the server child process started by startServer() */
let _serverPid = null;

// ─── Configuration ────────────────────────────────────────────────────────────

/**
 * Override host/port at runtime (e.g. after discoverPort() finds a live gateway).
 * Call this before any other method when connecting to a non-default port.
 */
function configure({ host, port } = {}) {
  if (host !== undefined) _host = host;
  if (port !== undefined) _port = port;
}

// ─── Low-level HTTP ───────────────────────────────────────────────────────────

/**
 * Make an HTTP request to the AlphaClaw server.
 *
 * @param {string} method     — "GET" | "POST" | "PUT"
 * @param {string} urlPath    — e.g. "/health", "/api/status"
 * @param {object} opts
 * @param {object|null} opts.body       — JSON body for POST/PUT
 * @param {number}      opts.timeout    — ms (default 8000)
 * @param {boolean}     opts.withCookie — attach session cookie (default true)
 * @returns {Promise<{status: number, body: any, headers: object}>}
 */
function _request(method, urlPath, opts = {}) {
  const { body = null, timeout = 8000, withCookie = true } = opts;
  return new Promise((resolve, reject) => {
    const bodyStr = body !== null ? JSON.stringify(body) : null;

    const headers = { "Content-Type": "application/json", Accept: "application/json" };
    if (withCookie && _cookie) headers["Cookie"] = _cookie;
    if (bodyStr) headers["Content-Length"] = Buffer.byteLength(bodyStr);

    const options = { hostname: _host, port: _port, path: urlPath, method, headers };

    const req = http.request(options, (res) => {
      // Capture Set-Cookie header on login response
      const rawCookies = res.headers["set-cookie"];
      if (rawCookies) {
        _cookie = rawCookies.map((c) => c.split(";")[0]).join("; ");
      }

      let data = "";
      res.on("data", (chunk) => (data += chunk));
      res.on("end", () => {
        let parsed;
        try {
          parsed = JSON.parse(data);
        } catch {
          parsed = data;
        }
        resolve({ status: res.statusCode, body: parsed, headers: res.headers });
      });
    });

    req.setTimeout(timeout, () => {
      req.destroy();
      reject(new Error(`HTTP timeout after ${timeout}ms: ${method} ${urlPath}`));
    });

    req.on("error", (e) =>
      reject(new Error(`HTTP error — ${e.message}: ${method} http://${_host}:${_port}${urlPath}`))
    );

    if (bodyStr) req.write(bodyStr);
    req.end();
  });
}

// ─── Auth ─────────────────────────────────────────────────────────────────────

/**
 * Authenticate with AlphaClaw. Stores session cookie on success.
 * Required before any session²-auth endpoints (models, env, watchdog).
 *
 * @param {string} password — value of SETUP_PASSWORD from AlphaClaw .env
 * @returns {Promise<{ok: boolean, authenticated: boolean, error?: string}>}
 */
async function login(password) {
  try {
    _cookie = null; // clear any stale cookie first
    const r = await _request("POST", "/api/auth/login", {
      body: { password },
      withCookie: false,
    });
    if (r.status === 200) {
      return { ok: true, authenticated: true };
    }
    return { ok: false, authenticated: false, status: r.status, body: r.body };
  } catch (e) {
    return { ok: false, authenticated: false, error: e.message };
  }
}

/**
 * Check current authentication status without modifying cookie state.
 * GET /api/auth/status → {authenticated: bool}
 */
async function authStatus() {
  try {
    const r = await _request("GET", "/api/auth/status");
    return { ok: r.status < 400, ...r.body };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

/**
 * Log out and clear session cookie.
 * POST /api/auth/logout
 */
async function logout() {
  try {
    await _request("POST", "/api/auth/logout");
  } finally {
    _cookie = null;
  }
  return { ok: true };
}

// ─── No-auth endpoints ────────────────────────────────────────────────────────

/**
 * Liveness probe. No auth required.
 * GET /health → {status:"ok"} | {status:"error"}
 */
async function health() {
  try {
    const r = await _request("GET", "/health", { withCookie: false, timeout: 4000 });
    return { ok: r.status === 200, status: r.status, body: r.body };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

/**
 * Onboarding status. No auth required.
 * GET /api/onboard/status → {onboarded:bool, ...}
 */
async function onboardStatus() {
  try {
    const r = await _request("GET", "/api/onboard/status", { withCookie: false });
    return { ok: r.status < 400, ...r.body };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

// ─── Setup-allowlisted endpoints ──────────────────────────────────────────────
// These are accessible during setup phase via SETUP_API_PREFIXES in
// AlphaClaw lib/server/constants.js:380. No full session auth required,
// though they accept a cookie if present.

/**
 * GET /api/status — server state + uptime.
 */
async function status() {
  try {
    const r = await _request("GET", "/api/status");
    return { ok: r.status < 400, status: r.status, body: r.body };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

/**
 * GET /api/gateway-status — gateway process health.
 */
async function gatewayStatus() {
  try {
    const r = await _request("GET", "/api/gateway-status");
    return { ok: r.status < 400, status: r.status, body: r.body };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

/**
 * GET /api/gateway/dashboard — full dashboard data (models, stats, connections).
 */
async function gatewayDashboard() {
  try {
    const r = await _request("GET", "/api/gateway/dashboard");
    return { ok: r.status < 400, status: r.status, body: r.body };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

/**
 * POST /api/gateway/restart — restart the OpenClaw gateway process.
 * Returns {ok:true} immediately; poll restartStatus() for completion.
 */
async function restartGateway() {
  try {
    const r = await _request("POST", "/api/gateway/restart", { body: {} });
    return { ok: r.status < 400, status: r.status, body: r.body };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

/**
 * GET /api/restart-status — query restart progress.
 */
async function restartStatus() {
  try {
    const r = await _request("GET", "/api/restart-status");
    return { ok: r.status < 400, status: r.status, body: r.body };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

/**
 * POST /api/restart-status/dismiss — dismiss the restart banner in the UI.
 */
async function dismissRestartStatus() {
  try {
    const r = await _request("POST", "/api/restart-status/dismiss", { body: {} });
    return { ok: r.status < 400, status: r.status, body: r.body };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

/**
 * GET /api/alphaclaw/version — version string.
 */
async function version() {
  try {
    const r = await _request("GET", "/api/alphaclaw/version");
    return {
      ok: r.status < 400,
      version: r.body?.version || r.body,
      body: r.body,
    };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

// ─── Session-auth endpoints ───────────────────────────────────────────────────
// These require a valid session cookie from login().
// On 401, callers should re-login and retry once.

/**
 * GET /api/models — full model list from all configured providers.
 */
async function getModels() {
  try {
    const r = await _request("GET", "/api/models");
    return { ok: r.status < 400, status: r.status, models: r.body?.models || r.body };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

/**
 * GET /api/models/config — routing config (providers, channels, active models).
 */
async function getModelsConfig() {
  try {
    const r = await _request("GET", "/api/models/config");
    return { ok: r.status < 400, status: r.status, config: r.body };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

/**
 * PUT /api/models/config — update routing config.
 * @param {object} config — new config payload (must match openclaw.json schema)
 */
async function putModelsConfig(config) {
  try {
    const r = await _request("PUT", "/api/models/config", { body: config });
    return { ok: r.status < 400, status: r.status, body: r.body };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

/**
 * GET /api/env — environment variables. PT MUST redact secrets before logging/use.
 * Invariant: any key matching /token|secret|password|key|auth|credential/i is redacted.
 */
async function getEnv() {
  try {
    const r = await _request("GET", "/api/env");
    const safe = {};
    for (const [k, v] of Object.entries(r.body || {})) {
      safe[k] = /token|secret|password|key|auth|credential/i.test(k) ? "[REDACTED]" : v;
    }
    return { ok: r.status < 400, status: r.status, env: safe };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

/**
 * PUT /api/env — write environment variables.
 * PT must strip secrets from logs; never log raw values.
 * @param {object} vars — key/value pairs to write
 */
async function putEnv(vars) {
  try {
    const r = await _request("PUT", "/api/env", { body: vars });
    return { ok: r.status < 400, status: r.status, body: r.body };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

// ─── Watchdog ─────────────────────────────────────────────────────────────────

/**
 * GET /api/watchdog/status — watchdog health state.
 */
async function watchdogStatus() {
  try {
    const r = await _request("GET", "/api/watchdog/status");
    return { ok: r.status < 400, status: r.status, body: r.body };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

/**
 * GET /api/watchdog/events — recent watchdog events.
 */
async function watchdogEvents() {
  try {
    const r = await _request("GET", "/api/watchdog/events");
    return { ok: r.status < 400, status: r.status, events: r.body };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

/**
 * GET /api/watchdog/logs — log tail.
 * @param {number} n — number of lines to return (default 50)
 */
async function watchdogLogs(n = 50) {
  try {
    const r = await _request("GET", `/api/watchdog/logs?lines=${n}`);
    return { ok: r.status < 400, status: r.status, logs: r.body };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

/**
 * POST /api/watchdog/repair — trigger self-repair.
 */
async function watchdogRepair() {
  try {
    const r = await _request("POST", "/api/watchdog/repair", { body: {} });
    return { ok: r.status < 400, status: r.status, body: r.body };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

/** Alias: tailLogs(n) → watchdogLogs(n) */
const tailLogs = watchdogLogs;

// ─── Port discovery (commandeer-first) ───────────────────────────────────────

/**
 * Try each candidate port in order; return the first that answers GET /health.
 *
 * Implements the commandeer-first daemon pattern: if a compatible gateway is
 * already running, reuse it — do NOT restart it.
 *
 * Side effect: calls configure({ port }) on success so all subsequent calls
 * use the discovered port.
 *
 * @param {string}   [host]      — host to probe (default DEFAULT_HOST)
 * @param {number[]} [ports]     — ordered candidate port list (default CANDIDATE_PORTS)
 * @param {number}   [timeoutMs] — per-port timeout in ms (default 2000)
 * @returns {Promise<{found: boolean, port?: number, host?: string}>}
 */
async function discoverPort(
  host = DEFAULT_HOST,
  ports = CANDIDATE_PORTS,
  timeoutMs = 2000
) {
  const savedPort = _port;
  const savedHost = _host;

  for (const p of ports) {
    _port = p;
    _host = host;
    try {
      const r = await _request("GET", "/health", { withCookie: false, timeout: timeoutMs });
      if (r.status === 200) {
        // keep the discovered port active for subsequent calls
        return { found: true, port: p, host };
      }
    } catch (_) {
      // this port not answering — try next
    }
  }

  // restore originals if nothing found
  _port = savedPort;
  _host = savedHost;
  return { found: false };
}

// ─── CLI lifecycle ────────────────────────────────────────────────────────────

/**
 * Start AlphaClaw as a detached background process.
 *
 * Idempotency: probes /health first. If already running, returns
 * { ok: true, already: true, port } without spawning a new process.
 *
 * @param {object} opts
 * @param {number} opts.port           — port to start on (default active _port)
 * @param {string} opts.alphaclawRoot  — override ALPHACLAW_ROOT
 * @param {string} opts.logFile        — if set, append stdout+stderr here
 * @returns {Promise<{ok: boolean, already?: boolean, pid?: number, port: number, error?: string}>}
 */
async function startServer({ port, alphaclawRoot, logFile } = {}) {
  const p = port || _port;
  const root = alphaclawRoot || ALPHACLAW_ROOT;

  // Commandeer-first: if already responding, reuse — don't restart
  const h = await health();
  if (h.ok) {
    return { ok: true, already: true, port: p };
  }

  const env = { ...process.env, PORT: String(p) };

  let stdio;
  if (logFile) {
    const fd = fs.openSync(logFile, "a");
    stdio = ["ignore", fd, fd];
  } else {
    stdio = ["ignore", "ignore", "ignore"];
  }

  try {
    const child = spawn("node", ["bin/alphaclaw.js", "start"], {
      cwd: root,
      env,
      detached: true,
      stdio,
    });
    child.unref(); // allow parent to exit independently
    _serverPid = child.pid;
    return { ok: true, pid: child.pid, port: p };
  } catch (e) {
    return { ok: false, error: e.message, port: p };
  }
}

/**
 * Poll GET /health until AlphaClaw responds or timeout is reached.
 * Use immediately after startServer() to wait for readiness.
 *
 * @param {object} opts
 * @param {number} opts.timeoutMs  — total wait time (default 30 000 ms)
 * @param {number} opts.intervalMs — poll interval (default 500 ms)
 * @returns {Promise<{ready: boolean, elapsed: number, error?: string}>}
 */
async function waitForReady({ timeoutMs = 30_000, intervalMs = 500 } = {}) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const h = await health();
    if (h.ok) return { ready: true, elapsed: Date.now() - start };
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  return { ready: false, elapsed: Date.now() - start, error: "timeout" };
}

/**
 * Ensure AlphaClaw is running. Discovers first (commandeer-first), then starts
 * if not found, then waits for readiness.
 *
 * This is the preferred lifecycle entrypoint for PT's orchestrator.
 *
 * @param {object} opts — forwarded to startServer()
 * @returns {Promise<{ok: boolean, port: number, commandeered?: boolean, started?: boolean, pid?: number, elapsed?: number, error?: string}>}
 */
async function ensureRunning(opts = {}) {
  // 1. Commandeer-first: find an existing gateway
  const found = await discoverPort();
  if (found.found) {
    return { ok: true, commandeered: true, port: found.port };
  }

  // 2. Start a new instance
  const started = await startServer(opts);
  if (!started.ok) return started;

  // 3. Wait for it to be ready
  const ready = await waitForReady();
  return {
    ok: ready.ready,
    started: true,
    port: started.port,
    pid: started.pid,
    elapsed: ready.elapsed,
    error: ready.error,
  };
}

// ─── Exports ──────────────────────────────────────────────────────────────────

module.exports = {
  // Runtime config
  configure,
  DEFAULT_PORT,
  DEFAULT_HOST,
  ALPHACLAW_ROOT,
  CANDIDATE_PORTS,

  // Auth
  login,
  logout,
  authStatus,

  // No-auth
  health,
  onboardStatus,

  // Setup-allowlisted (no session needed)
  status,
  gatewayStatus,
  gatewayDashboard,
  restartGateway,
  restartStatus,
  dismissRestartStatus,
  version,

  // Session-auth (call login() first)
  getModels,
  getModelsConfig,
  putModelsConfig,
  getEnv,
  putEnv,

  // Watchdog (session-auth)
  watchdogStatus,
  watchdogEvents,
  watchdogLogs,
  watchdogRepair,
  tailLogs,

  // Port discovery + lifecycle
  discoverPort,
  startServer,
  waitForReady,
  ensureRunning,
};
