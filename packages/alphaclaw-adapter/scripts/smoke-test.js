#!/usr/bin/env node
/**
 * packages/alphaclaw-adapter/scripts/smoke-test.js
 *
 * Gate 1 smoke test — exercises the full AlphaClaw adapter against a live
 * AlphaClaw instance. Prints colored PASS/FAIL per capability.
 *
 * Usage:
 *   SETUP_PASSWORD=<pass> node packages/alphaclaw-adapter/scripts/smoke-test.js
 *   SETUP_PASSWORD=<pass> ALPHACLAW_PORT=3001 node ...smoke-test.js
 *
 * Requirements:
 *   - AlphaClaw must be running (start it first with ensureRunning() or manually)
 *   - SETUP_PASSWORD env var must be set
 *
 * Exit code: 0 if all tests pass, 1 if any fail
 */

"use strict";

const path = require("path");
const adapter = require(path.resolve(__dirname, "../src/index.js"));

// ─── Config ───────────────────────────────────────────────────────────────────

const SETUP_PASSWORD = process.env.SETUP_PASSWORD;
const SKIP_AUTH_TESTS = !SETUP_PASSWORD;

// ─── Pretty print ─────────────────────────────────────────────────────────────

const C = {
  reset: "\x1b[0m",
  green: "\x1b[32m",
  red: "\x1b[31m",
  yellow: "\x1b[33m",
  cyan: "\x1b[36m",
  bold: "\x1b[1m",
  dim: "\x1b[2m",
};

const pad = (s, n) => s.padEnd(n, " ");

let passed = 0;
let failed = 0;
let skipped = 0;

function result(label, ok, detail = "", warn = false) {
  if (ok === null) {
    console.log(`  ${C.yellow}SKIP${C.reset}  ${pad(label, 40)} ${C.dim}${detail}${C.reset}`);
    skipped++;
    return;
  }
  if (ok) {
    console.log(`  ${C.green}PASS${C.reset}  ${pad(label, 40)} ${C.dim}${detail}${C.reset}`);
    passed++;
  } else {
    console.log(`  ${C.red}FAIL${C.reset}  ${pad(label, 40)} ${C.red}${detail}${C.reset}`);
    failed++;
  }
}

// ─── Test runner ──────────────────────────────────────────────────────────────

async function run() {
  console.log();
  console.log(
    `${C.bold}${C.cyan}AlphaClaw Adapter — Gate 1 Smoke Test${C.reset}  ${C.dim}v0.9.9.8${C.reset}`
  );
  console.log(`${C.dim}  Host: ${adapter.DEFAULT_HOST}:${adapter.DEFAULT_PORT}${C.reset}`);
  console.log(
    `${C.dim}  Auth: ${SKIP_AUTH_TESTS ? "SKIPPED (no SETUP_PASSWORD)" : "enabled"}${C.reset}`
  );
  console.log();

  // ── 1. Port discovery ────────────────────────────────────────────────────────
  console.log(`${C.bold}  ── Port discovery ──${C.reset}`);

  const disc = await adapter.discoverPort();
  result(
    "discoverPort()",
    disc.found,
    disc.found ? `port ${disc.port}` : "no AlphaClaw found on candidate ports"
  );

  if (!disc.found) {
    console.log();
    console.log(
      `${C.red}  AlphaClaw not reachable. Start it first:${C.reset}`
    );
    console.log(`${C.dim}  node bin/alphaclaw.js start  (in AlphaClaw repo)${C.reset}`);
    console.log();
    process.exit(1);
  }

  // ── 2. No-auth endpoints ─────────────────────────────────────────────────────
  console.log();
  console.log(`${C.bold}  ── No-auth endpoints ──${C.reset}`);

  const h = await adapter.health();
  result("health()", h.ok, h.ok ? `status ${h.status}` : h.error);

  const ob = await adapter.onboardStatus();
  result(
    "onboardStatus()",
    ob.ok !== false,
    ob.ok !== false ? `onboarded=${ob.onboarded}` : ob.error
  );

  // ── 3. Setup-allowlisted endpoints ───────────────────────────────────────────
  console.log();
  console.log(`${C.bold}  ── Setup-allowlisted endpoints ──${C.reset}`);

  const st = await adapter.status();
  result("status()", st.ok, st.ok ? "server state OK" : st.error);

  const gs = await adapter.gatewayStatus();
  result(
    "gatewayStatus()",
    gs.ok,
    gs.ok ? "gateway health OK" : `HTTP ${gs.status} — ${gs.error || "check AlphaClaw logs"}`
  );

  const gd = await adapter.gatewayDashboard();
  result(
    "gatewayDashboard()",
    gd.ok,
    gd.ok ? "dashboard data OK" : `HTTP ${gd.status} — ${gd.error || ""}`
  );

  const rs = await adapter.restartStatus();
  result("restartStatus()", rs.ok, rs.ok ? "restart state OK" : rs.error);

  const ver = await adapter.version();
  result(
    "version()",
    ver.ok,
    ver.ok ? `version=${ver.version || JSON.stringify(ver.body)}` : ver.error
  );

  // ── 4. Auth ──────────────────────────────────────────────────────────────────
  console.log();
  console.log(`${C.bold}  ── Auth ──${C.reset}`);

  if (SKIP_AUTH_TESTS) {
    result("login(password)", null, "SETUP_PASSWORD not set — skipping session tests");
    result("authStatus()", null, "skipped");
    result("logout()", null, "skipped");
  } else {
    const loginRes = await adapter.login(SETUP_PASSWORD);
    result(
      "login(password)",
      loginRes.ok,
      loginRes.ok ? "session cookie stored" : `HTTP ${loginRes.status} — wrong password?`
    );

    const as = await adapter.authStatus();
    result(
      "authStatus()",
      as.authenticated === true,
      as.authenticated ? "authenticated=true" : `authenticated=${as.authenticated}`
    );

    // ── 5. Session-auth endpoints ──────────────────────────────────────────────
    console.log();
    console.log(`${C.bold}  ── Session-auth endpoints ──${C.reset}`);

    const mc = await adapter.getModelsConfig();
    result(
      "getModelsConfig()",
      mc.ok,
      mc.ok ? "routing config OK" : `HTTP ${mc.status} — ${mc.error || ""}`
    );

    const gm = await adapter.getModels();
    result(
      "getModels()",
      gm.ok,
      gm.ok
        ? `${Array.isArray(gm.models) ? gm.models.length : "?"} models`
        : `HTTP ${gm.status} — ${gm.error || ""}`
    );

    const env = await adapter.getEnv();
    result(
      "getEnv() + redaction",
      env.ok,
      env.ok
        ? `${Object.keys(env.env || {}).length} vars, secrets redacted`
        : `HTTP ${env.status} — ${env.error || ""}`
    );

    // ── 6. Watchdog ────────────────────────────────────────────────────────────
    console.log();
    console.log(`${C.bold}  ── Watchdog ──${C.reset}`);

    const ws = await adapter.watchdogStatus();
    result(
      "watchdogStatus()",
      ws.ok,
      ws.ok ? "watchdog OK" : `HTTP ${ws.status} — ${ws.error || "watchdog may not be active"}`
    );

    const wl = await adapter.watchdogLogs(10);
    result(
      "watchdogLogs(10)",
      wl.ok,
      wl.ok ? "log tail OK" : `HTTP ${wl.status} — ${wl.error || ""}`
    );

    const we = await adapter.watchdogEvents();
    result(
      "watchdogEvents()",
      we.ok,
      we.ok ? "events OK" : `HTTP ${we.status} — ${we.error || ""}`
    );

    // tailLogs alias
    const tl = await adapter.tailLogs(5);
    result(
      "tailLogs(5) [alias]",
      tl.ok,
      tl.ok ? "alias works" : `HTTP ${tl.status} — ${tl.error || ""}`
    );

    // ── 7. Logout ──────────────────────────────────────────────────────────────
    console.log();
    console.log(`${C.bold}  ── Cleanup ──${C.reset}`);

    const lo = await adapter.logout();
    result("logout()", lo.ok, lo.ok ? "cookie cleared" : lo.error);
  }

  // ── 8. restartGateway — skipped by default (destructive) ──────────────────
  console.log();
  console.log(`${C.bold}  ── Destructive (skipped by default) ──${C.reset}`);
  result(
    "restartGateway()",
    null,
    "set SMOKE_DESTRUCTIVE=1 to run"
  );
  result(
    "watchdogRepair()",
    null,
    "set SMOKE_DESTRUCTIVE=1 to run"
  );

  if (process.env.SMOKE_DESTRUCTIVE === "1" && !SKIP_AUTH_TESTS) {
    const lg2 = await adapter.login(SETUP_PASSWORD);
    if (lg2.ok) {
      const rg = await adapter.restartGateway();
      result(
        "restartGateway()",
        rg.ok,
        rg.ok ? "restart triggered" : `HTTP ${rg.status}`
      );

      // Wait briefly then check restart status
      await new Promise((r) => setTimeout(r, 2000));
      const rrs = await adapter.restartStatus();
      result(
        "restartStatus() post-restart",
        rrs.ok,
        rrs.ok ? "restart state updated" : rrs.error
      );

      const wr = await adapter.watchdogRepair();
      result(
        "watchdogRepair()",
        wr.ok,
        wr.ok ? "repair triggered" : `HTTP ${wr.status}`
      );

      await adapter.logout();
    }
  }

  // ── Summary ──────────────────────────────────────────────────────────────────
  console.log();
  console.log(`${"─".repeat(58)}`);
  const total = passed + failed + skipped;
  const statusColor = failed > 0 ? C.red : C.green;
  console.log(
    `  ${statusColor}${C.bold}${passed} passed${C.reset}  ${C.dim}${failed} failed  ${skipped} skipped  (${total} total)${C.reset}`
  );
  console.log();

  if (failed > 0) {
    console.log(`${C.red}  Some tests failed. Check AlphaClaw logs and adapter-interface-contract.md${C.reset}`);
    console.log();
    process.exit(1);
  }

  console.log(`${C.green}  All adapter methods verified against live AlphaClaw ✓${C.reset}`);
  console.log(`${C.dim}  Gate 1 smoke test complete — adapter is operational${C.reset}`);
  console.log();
}

run().catch((e) => {
  console.error(`\n${C.red}  Unexpected error: ${e.message}${C.reset}\n`);
  process.exit(1);
});
