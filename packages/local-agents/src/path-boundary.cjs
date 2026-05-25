/**
 * MCP path boundary — approved repo roots only (security fix 4).
 *
 * - Caller paths must resolve under configured roots (ALPHACLAW_ROOT, etc.).
 * - Absolute paths outside roots are rejected.
 * - Symlink escapes are blocked via realpath when the target exists.
 * - Log/config text uses the same redaction patterns as orchestrator/redaction.py.
 */

"use strict";

const fs = require("fs");
const path = require("path");

const _SECRET_PATTERNS = [
  /\bAIza[0-9A-Za-z_-]{20,}\b/g,
  /\b\d{8,10}:[A-Za-z0-9_-]{30,}\b/g,
  /\bghp_[0-9A-Za-z]{20,}\b/g,
  /\bsk-[A-Za-z0-9]{20,}\b/g,
  /\bsk-ant-[A-Za-z0-9_-]{20,}\b/g,
  /\bBearer\s+[A-Za-z0-9._-]{20,}\b/gi,
];
const _EMAIL_PATTERN = /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g;
const _REDACTED = "[REDACTED]";

/** Env vars that define approved filesystem roots (colon-separated lists allowed). */
const _ROOT_ENV_KEYS = [
  "MCP_APPROVED_ROOTS",
  "ALPHACLAW_ROOT",
  "PERPETUA_TOOLS_ROOT",
  "ORAMA_SYSTEM_ROOT",
  "OPENCLAW_ROOT",
];

function _splitEnvRoots(value) {
  if (!value || typeof value !== "string") return [];
  return value
    .split(path.delimiter)
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => path.resolve(part));
}

/**
 * @returns {string[]} deduplicated absolute root directories
 */
function getApprovedRoots(extraRoots = []) {
  const roots = [];
  for (const key of _ROOT_ENV_KEYS) {
    roots.push(..._splitEnvRoots(process.env[key]));
  }
  for (const r of extraRoots) {
    if (r) roots.push(path.resolve(r));
  }
  if (roots.length === 0) {
    // Perpetua-Tools repo root when invoked from packages/local-agents
    roots.push(path.resolve(__dirname, "..", "..", ".."));
  }
  return [...new Set(roots)];
}

function _realpathSafe(p) {
  try {
    return fs.existsSync(p) ? fs.realpathSync(p) : path.resolve(p);
  } catch {
    return path.resolve(p);
  }
}

function _isUnderRoot(resolvedPath, root) {
  const resolvedRoot = _realpathSafe(root);
  const resolvedTarget = _realpathSafe(resolvedPath);
  const rel = path.relative(resolvedRoot, resolvedTarget);
  return rel === "" || (!rel.startsWith("..") && !path.isAbsolute(rel));
}

/**
 * Resolve and authorize a filesystem path under approved roots.
 *
 * @param {string} inputPath
 * @param {{ roots?: string[], mustExist?: boolean, baseForRelative?: string }} [opts]
 */
function resolveAllowedPath(inputPath, opts = {}) {
  const roots = opts.roots?.length ? opts.roots.map((r) => path.resolve(r)) : getApprovedRoots();
  const mustExist = opts.mustExist !== false;

  if (!inputPath || typeof inputPath !== "string") {
    return { ok: false, error: "path required" };
  }
  if (inputPath.includes("\0")) {
    return { ok: false, error: "invalid path" };
  }

  const baseForRelative = opts.baseForRelative
    ? path.resolve(opts.baseForRelative)
    : roots[0] || process.cwd();

  const candidate = path.isAbsolute(inputPath)
    ? path.resolve(inputPath)
    : path.resolve(baseForRelative, inputPath);

  let matchedRoot = null;
  for (const root of roots) {
    if (_isUnderRoot(candidate, root)) {
      matchedRoot = root;
      break;
    }
  }

  if (!matchedRoot) {
    return {
      ok: false,
      error: `path outside approved MCP roots: ${candidate}`,
      candidate,
      roots,
      rejectedOutsideRoots: true,
    };
  }

  if (!mustExist) {
    return { ok: true, abs: candidate, root: matchedRoot };
  }

  if (!fs.existsSync(candidate)) {
    return { ok: false, error: `path not found: ${candidate}`, candidate, root: matchedRoot };
  }

  let abs = candidate;
  try {
    abs = fs.realpathSync(candidate);
  } catch (err) {
    return { ok: false, error: err.message, candidate, root: matchedRoot };
  }

  if (!_isUnderRoot(abs, matchedRoot)) {
    return {
      ok: false,
      error: "path escapes approved root via symlink",
      candidate,
      abs,
      root: matchedRoot,
    };
  }

  return { ok: true, abs, root: matchedRoot };
}

/**
 * Redact secrets and emails from log or file text before MCP responses.
 * @param {string} text
 */
function redactLogText(text) {
  if (!text || typeof text !== "string") return text;
  let out = text;
  for (const pattern of _SECRET_PATTERNS) {
    out = out.replace(pattern, _REDACTED);
  }
  out = out.replace(_EMAIL_PATTERN, _REDACTED);
  // .env-style assignment lines for common secret keys
  out = out.replace(
    /^(\s*(?:SETUP_PASSWORD|API_KEY|TOKEN|SECRET|PASSWORD)\s*=\s*).+$/gim,
    `$1${_REDACTED}`
  );
  return out;
}

module.exports = {
  getApprovedRoots,
  resolveAllowedPath,
  redactLogText,
};
