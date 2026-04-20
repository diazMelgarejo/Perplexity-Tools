#!/usr/bin/env node
/**
 * local-agent-client.js — AlphaClaw Local AI Agent Client
 *
 * Connects to Ollama and LM Studio instances running on the user's Mac.
 * Used by the orchestration layer to dispatch code-reading/writing subtasks
 * to local models, keeping main Claude as planner/reviewer.
 *
 * Endpoints (configurable via env or constructor):
 *   Ollama:    http://127.0.0.1:11435  (try GLM-5.1:cloud → qwen3.5-local:latest)
 *   LM Studio: http://192.168.254.101:1234  (OpenAI-compatible)
 *
 * API compatibility:
 *   Ollama    → native /api/generate  +  OpenAI-compat /v1/chat/completions
 *   LM Studio → OpenAI-compat /v1/chat/completions
 *
 * Usage:
 *   const { LocalAgentClient } = require('./local-agent-client');
 *   const client = new LocalAgentClient();
 *   const result = await client.complete({ prompt: 'Read this code: ...' });
 */

"use strict";

const http  = require("http");
const https = require("https");
const { URL } = require("url");

// ─── Configuration ─────────────────────────────────────────────────────────────

const DEFAULTS = {
  ollama: {
    baseUrl:  process.env.OLLAMA_BASE_URL  || "http://127.0.0.1:11435",
    models:   (process.env.OLLAMA_MODELS   || "GLM-5.1:cloud,qwen3.5-local:latest").split(",").map(m => m.trim()),
    timeoutMs: parseInt(process.env.OLLAMA_TIMEOUT_MS || "30000", 10),
  },
  lmstudio: {
    baseUrl:  process.env.LMSTUDIO_BASE_URL || "http://192.168.254.101:1234",
    timeoutMs: parseInt(process.env.LMSTUDIO_TIMEOUT_MS || "30000", 10),
  },
};

// ─── Low-level HTTP helper ─────────────────────────────────────────────────────

/**
 * Minimal JSON HTTP client — no external deps.
 * Returns { ok, status, data } or throws on network error.
 */
function httpRequest(method, urlStr, body, timeoutMs = 15000) {
  return new Promise((resolve, reject) => {
    let url;
    try { url = new URL(urlStr); } catch (e) {
      return reject(new Error(`Invalid URL: ${urlStr} — ${e.message}`));
    }

    const lib = url.protocol === "https:" ? https : http;
    const payload = body ? JSON.stringify(body) : null;

    const options = {
      hostname: url.hostname,
      port:     url.port || (url.protocol === "https:" ? 443 : 80),
      path:     url.pathname + url.search,
      method,
      headers:  {
        "Content-Type":  "application/json",
        "Accept":        "application/json",
        ...(payload ? { "Content-Length": Buffer.byteLength(payload) } : {}),
      },
    };

    const req = lib.request(options, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end",  () => {
        const raw = Buffer.concat(chunks).toString("utf8");
        let data;
        try { data = JSON.parse(raw); } catch { data = raw; }
        resolve({ ok: res.statusCode >= 200 && res.statusCode < 300, status: res.statusCode, data });
      });
    });

    req.setTimeout(timeoutMs, () => {
      req.destroy(new Error(`Request timed out after ${timeoutMs}ms`));
    });

    req.on("error", (e) => reject(new Error(`HTTP ${method} ${urlStr} failed: ${e.message}`)));

    if (payload) req.write(payload);
    req.end();
  });
}

// ─── Ollama Client ─────────────────────────────────────────────────────────────

class OllamaClient {
  constructor(opts = {}) {
    this.baseUrl   = (opts.baseUrl   || DEFAULTS.ollama.baseUrl).replace(/\/$/, "");
    this.models    = opts.models     || DEFAULTS.ollama.models;
    this.timeoutMs = opts.timeoutMs  || DEFAULTS.ollama.timeoutMs;
    this._activeModel = null;
  }

  /** List models available on this Ollama instance. */
  async listModels() {
    const r = await httpRequest("GET", `${this.baseUrl}/api/tags`, null, this.timeoutMs);
    if (!r.ok) throw new Error(`Ollama listModels failed (${r.status})`);
    return (r.data.models || []).map(m => m.name || m.model || String(m));
  }

  /** Pick the first preferred model that is actually loaded. */
  async resolveModel() {
    if (this._activeModel) return this._activeModel;
    let available = [];
    try { available = await this.listModels(); } catch (e) {
      throw new Error(`Ollama not reachable at ${this.baseUrl}: ${e.message}`);
    }
    for (const preferred of this.models) {
      const match = available.find(
        m => m === preferred || m.startsWith(preferred.split(":")[0])
      );
      if (match) { this._activeModel = match; return match; }
    }
    // Fallback: just use the first available model
    if (available.length > 0) {
      this._activeModel = available[0];
      return available[0];
    }
    throw new Error(`No preferred models (${this.models.join(", ")}) found in Ollama. Available: ${available.join(", ") || "none"}`);
  }

  /**
   * Send a prompt via OpenAI-compat endpoint (Ollama ≥ 0.1.24 supports this).
   * Falls back to native /api/generate if needed.
   */
  async complete({ prompt, systemPrompt, maxTokens = 2048, temperature = 0.2 }) {
    const model = await this.resolveModel();

    // Prefer OpenAI-compat endpoint (easier to unify with LM Studio)
    const messages = [];
    if (systemPrompt) messages.push({ role: "system",    content: systemPrompt });
    messages.push(               { role: "user",      content: prompt      });

    try {
      const r = await httpRequest(
        "POST",
        `${this.baseUrl}/v1/chat/completions`,
        { model, messages, max_tokens: maxTokens, temperature, stream: false },
        this.timeoutMs
      );
      if (r.ok) {
        const text = r.data?.choices?.[0]?.message?.content || "";
        return { ok: true, model, backend: "ollama", text, raw: r.data };
      }
    } catch (_) { /* fall through to native API */ }

    // Native Ollama /api/generate
    const nativePrompt = systemPrompt ? `${systemPrompt}\n\n${prompt}` : prompt;
    const r2 = await httpRequest(
      "POST",
      `${this.baseUrl}/api/generate`,
      { model, prompt: nativePrompt, stream: false, options: { temperature, num_predict: maxTokens } },
      this.timeoutMs
    );
    if (!r2.ok) throw new Error(`Ollama generate failed (${r2.status}): ${JSON.stringify(r2.data)}`);
    return { ok: true, model, backend: "ollama", text: r2.data.response || "", raw: r2.data };
  }

  /** Health check — returns { ok, model, available } */
  async ping() {
    try {
      const model = await this.resolveModel();
      return { ok: true, model, backend: "ollama", baseUrl: this.baseUrl };
    } catch (e) {
      return { ok: false, backend: "ollama", baseUrl: this.baseUrl, error: e.message };
    }
  }
}

// ─── LM Studio Client ──────────────────────────────────────────────────────────

class LMStudioClient {
  constructor(opts = {}) {
    this.baseUrl   = (opts.baseUrl   || DEFAULTS.lmstudio.baseUrl).replace(/\/$/, "");
    this.timeoutMs = opts.timeoutMs  || DEFAULTS.lmstudio.timeoutMs;
    this._activeModel = null;
  }

  async listModels() {
    const r = await httpRequest("GET", `${this.baseUrl}/v1/models`, null, this.timeoutMs);
    if (!r.ok) throw new Error(`LM Studio listModels failed (${r.status})`);
    return (r.data.data || []).map(m => m.id || String(m));
  }

  async resolveModel() {
    if (this._activeModel) return this._activeModel;
    let models = [];
    try { models = await this.listModels(); } catch (e) {
      throw new Error(`LM Studio not reachable at ${this.baseUrl}: ${e.message}`);
    }
    if (models.length === 0) throw new Error("LM Studio has no models loaded");
    this._activeModel = models[0];
    return models[0];
  }

  async complete({ prompt, systemPrompt, maxTokens = 2048, temperature = 0.2 }) {
    const model = await this.resolveModel();
    const messages = [];
    if (systemPrompt) messages.push({ role: "system", content: systemPrompt });
    messages.push(               { role: "user",   content: prompt      });

    const r = await httpRequest(
      "POST",
      `${this.baseUrl}/v1/chat/completions`,
      { model, messages, max_tokens: maxTokens, temperature, stream: false },
      this.timeoutMs
    );
    if (!r.ok) throw new Error(`LM Studio complete failed (${r.status}): ${JSON.stringify(r.data)}`);
    const text = r.data?.choices?.[0]?.message?.content || "";
    return { ok: true, model, backend: "lmstudio", text, raw: r.data };
  }

  async ping() {
    try {
      const model = await this.resolveModel();
      return { ok: true, model, backend: "lmstudio", baseUrl: this.baseUrl };
    } catch (e) {
      return { ok: false, backend: "lmstudio", baseUrl: this.baseUrl, error: e.message };
    }
  }
}

// ─── Unified LocalAgentClient (orchestrator-facing API) ───────────────────────

class LocalAgentClient {
  constructor(opts = {}) {
    this.ollama   = new OllamaClient(opts.ollama   || {});
    this.lmstudio = new LMStudioClient(opts.lmstudio || {});
    // Preference order: ollama first (local, faster), lmstudio as fallback
    this._preferenceOrder = opts.preferenceOrder || ["ollama", "lmstudio"];
  }

  /**
   * Complete a prompt using the best available local agent.
   * Tries backends in preference order, falls back on error.
   *
   * @param {object} opts
   * @param {string} opts.prompt        - The user/task prompt
   * @param {string} [opts.systemPrompt] - Optional system context
   * @param {number} [opts.maxTokens]   - Max output tokens
   * @param {number} [opts.temperature] - Sampling temperature
   * @param {string} [opts.backend]     - Force "ollama" or "lmstudio"
   * @returns {Promise<{ok, model, backend, text, error?}>}
   */
  async complete(opts) {
    const order = opts.backend
      ? [opts.backend, ...this._preferenceOrder.filter(b => b !== opts.backend)]
      : this._preferenceOrder;

    const errors = [];
    for (const backend of order) {
      try {
        const client = backend === "ollama" ? this.ollama : this.lmstudio;
        return await client.complete(opts);
      } catch (e) {
        errors.push(`${backend}: ${e.message}`);
      }
    }
    return { ok: false, text: "", errors, error: `All backends failed:\n  ${errors.join("\n  ")}` };
  }

  /**
   * Check availability of all backends.
   * @returns {Promise<{ollama, lmstudio, anyAvailable}>}
   */
  async healthCheck() {
    const [ollamaStatus, lmstudioStatus] = await Promise.allSettled([
      this.ollama.ping(),
      this.lmstudio.ping(),
    ]);

    const ollama   = ollamaStatus.status   === "fulfilled" ? ollamaStatus.value   : { ok: false, error: ollamaStatus.reason?.message };
    const lmstudio = lmstudioStatus.status === "fulfilled" ? lmstudioStatus.value : { ok: false, error: lmstudioStatus.reason?.message };

    return { ollama, lmstudio, anyAvailable: ollama.ok || lmstudio.ok };
  }

  /**
   * List all models across both backends.
   * @returns {Promise<{ollama: string[], lmstudio: string[]}>}
   */
  async listAllModels() {
    const results = { ollama: [], lmstudio: [], errors: {} };

    await Promise.allSettled([
      this.ollama.listModels().then(m => { results.ollama = m; }),
      this.lmstudio.listModels().then(m => { results.lmstudio = m; }),
    ]).then(settled => {
      if (settled[0].status === "rejected") results.errors.ollama   = settled[0].reason?.message;
      if (settled[1].status === "rejected") results.errors.lmstudio = settled[1].reason?.message;
    });

    return results;
  }
}

// ─── Code-specific helpers (used by orchestrator) ──────────────────────────────

/**
 * Ask a local agent to read a file and answer a question about it.
 * Returns the agent's text response.
 */
async function askLocalAgentAboutCode(client, { filePath, fileContent, question }) {
  const systemPrompt = [
    "You are a code analysis assistant. Read the provided source file carefully.",
    "Answer the question concisely and accurately.",
    "Output only the answer — no preamble, no apologies.",
  ].join(" ");

  const prompt = [
    `File: ${filePath}`,
    "```",
    fileContent.slice(0, 12000), // cap at ~12k chars to stay within context
    "```",
    "",
    `Question: ${question}`,
  ].join("\n");

  return client.complete({ prompt, systemPrompt, maxTokens: 1024, temperature: 0.1 });
}

/**
 * Ask a local agent to propose an edit to a file.
 * Returns { ok, proposedPatch, explanation } — Claude reviews before applying.
 */
async function proposeCodeEdit(client, { filePath, fileContent, instruction }) {
  const systemPrompt = [
    "You are a code editing assistant. You will be given a source file and an instruction.",
    "Respond with ONLY a unified diff (patch format) showing the minimal change needed.",
    "Do not include explanations before or after the diff.",
    "If no change is needed, respond with the single word: NOCHANGE",
  ].join(" ");

  const prompt = [
    `File: ${filePath}`,
    "```",
    fileContent.slice(0, 12000),
    "```",
    "",
    `Instruction: ${instruction}`,
  ].join("\n");

  const result = await client.complete({ prompt, systemPrompt, maxTokens: 2048, temperature: 0.1 });

  if (!result.ok) return { ok: false, error: result.error };

  const text = result.text.trim();
  if (text === "NOCHANGE") return { ok: true, proposedPatch: null, explanation: "No change needed" };

  // Extract diff if wrapped in code fences
  const diffMatch = text.match(/```(?:diff|patch)?\n([\s\S]+?)```/) ;
  const patch = diffMatch ? diffMatch[1] : text;

  return { ok: true, proposedPatch: patch, model: result.model, backend: result.backend };
}

// ─── Exports ───────────────────────────────────────────────────────────────────

module.exports = {
  LocalAgentClient,
  OllamaClient,
  LMStudioClient,
  askLocalAgentAboutCode,
  proposeCodeEdit,
  DEFAULTS,
};
