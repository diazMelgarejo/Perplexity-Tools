#!/usr/bin/env node
/**
 * orchestrator.js — AlphaClaw Local Agent Orchestrator
 *
 * Implements the planning/execution split:
 *   - Claude (main) = planner, reviewer, decision-maker
 *   - Local agents (Ollama / LM Studio) = code readers + writers
 *
 * Pattern:
 *   1. Claude emits a TASK (file + instruction)
 *   2. Orchestrator dispatches to best available local agent
 *   3. Local agent returns result / proposed patch
 *   4. Claude reviews and applies (or rejects)
 *
 * This module is also exposed as MCP tools via alphaclaw-mcp.js.
 */

"use strict";

const fs   = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const {
  LocalAgentClient,
  askLocalAgentAboutCode,
  proposeCodeEdit,
} = require("./local-agent-client");

// ─── Singleton client (lazy-init, reused across MCP tool calls) ───────────────
let _client = null;
function getClient() {
  if (!_client) _client = new LocalAgentClient();
  return _client;
}

// ─── Safe file reader (caps size, returns error if missing) ───────────────────
function readFileSafe(filePath, maxBytes = 64 * 1024) {
  const abs = path.isAbsolute(filePath) ? filePath : path.resolve(process.cwd(), filePath);
  if (!fs.existsSync(abs)) return { ok: false, error: `File not found: ${abs}`, abs };
  const stat = fs.statSync(abs);
  if (stat.size > maxBytes) {
    const content = fs.readFileSync(abs, "utf8").slice(0, maxBytes);
    return { ok: true, abs, content, truncated: true, originalSize: stat.size };
  }
  return { ok: true, abs, content: fs.readFileSync(abs, "utf8"), truncated: false };
}

// ─── Orchestrator tasks ────────────────────────────────────────────────────────

/**
 * Health check — which local agents are reachable?
 */
async function checkAgentHealth() {
  const client = getClient();
  return client.healthCheck();
}

/**
 * List all models available across Ollama + LM Studio.
 */
async function listLocalModels() {
  const client = getClient();
  return client.listAllModels();
}

/**
 * Dispatch a code question to a local agent.
 * Claude calls this when it wants a second opinion or needs to read a large file.
 *
 * @param {object} opts
 * @param {string} opts.filePath  - Path to the file (relative to project root or absolute)
 * @param {string} opts.question  - What to ask about the file
 * @param {string} [opts.backend] - Force "ollama" or "lmstudio"
 */
async function delegateCodeQuestion({ filePath, question, backend }) {
  const file = readFileSafe(filePath);
  if (!file.ok) return file;

  const client = getClient();
  const result = await askLocalAgentAboutCode(client, {
    filePath:    file.abs,
    fileContent: file.content,
    question,
  });

  return {
    ok:       result.ok,
    filePath: file.abs,
    truncated: file.truncated || false,
    question,
    answer:   result.text,
    model:    result.model,
    backend:  result.backend,
    error:    result.error,
  };
}

/**
 * Ask a local agent to propose an edit.
 * Returns a diff for Claude to review — does NOT apply automatically.
 *
 * @param {object} opts
 * @param {string} opts.filePath    - Path to the file
 * @param {string} opts.instruction - What change to make
 * @param {string} [opts.backend]   - Force "ollama" or "lmstudio"
 */
async function delegateCodeEdit({ filePath, instruction, backend }) {
  const file = readFileSafe(filePath);
  if (!file.ok) return file;

  const client = getClient();
  const result = await proposeCodeEdit(client, {
    filePath:    file.abs,
    fileContent: file.content,
    instruction,
  });

  return {
    ok:           result.ok,
    filePath:     file.abs,
    truncated:    file.truncated || false,
    instruction,
    proposedPatch: result.proposedPatch,
    explanation:  result.explanation,
    model:        result.model,
    backend:      result.backend,
    error:        result.error,
    // Remind Claude to review before applying
    reviewNote:   result.proposedPatch
      ? "⚠ Claude must review this patch before applying. Use `git apply --check` to validate."
      : null,
  };
}

/**
 * Ask a local agent to summarize a directory tree for planning.
 * Useful before large refactors — Claude stays as orchestrator.
 *
 * @param {object} opts
 * @param {string} opts.dirPath     - Directory to summarize
 * @param {string} opts.objective   - What are we trying to do?
 * @param {number} [opts.maxFiles]  - Cap on files to include (default 20)
 */
async function delegateCodeReview({ dirPath, objective, maxFiles = 20 }) {
  const abs = path.isAbsolute(dirPath) ? dirPath : path.resolve(process.cwd(), dirPath);
  if (!fs.existsSync(abs)) return { ok: false, error: `Directory not found: ${abs}` };

  // Build a compact file listing
  let files = [];
  try {
    const out = execSync(`find "${abs}" -type f -name "*.js" -o -name "*.ts" -o -name "*.json" 2>/dev/null | head -${maxFiles * 2}`, { encoding: "utf8" });
    files = out.trim().split("\n").filter(Boolean).slice(0, maxFiles);
  } catch (e) {
    return { ok: false, error: `Could not list files: ${e.message}` };
  }

  if (files.length === 0) return { ok: false, error: "No JS/TS/JSON files found in directory" };

  // Build a summary of first few lines of each file
  const snippets = files.map(f => {
    try {
      const lines = fs.readFileSync(f, "utf8").split("\n").slice(0, 8).join("\n");
      return `=== ${path.relative(abs, f)} ===\n${lines}`;
    } catch { return `=== ${path.relative(abs, f)} === [unreadable]`; }
  });

  const client = getClient();
  const result = await client.complete({
    systemPrompt: "You are a code architecture assistant. Analyze the provided file snippets and answer the question about the codebase structure. Be concise.",
    prompt: `Directory: ${abs}\nObjective: ${objective}\n\nFile snippets:\n\n${snippets.join("\n\n")}`,
    maxTokens: 1500,
    temperature: 0.2,
  });

  return {
    ok:        result.ok,
    dirPath:   abs,
    fileCount: files.length,
    objective,
    analysis:  result.text,
    model:     result.model,
    backend:   result.backend,
    error:     result.error,
  };
}

// ─── Exports ───────────────────────────────────────────────────────────────────

module.exports = {
  checkAgentHealth,
  listLocalModels,
  delegateCodeQuestion,
  delegateCodeEdit,
  delegateCodeReview,
  getClient,
};
