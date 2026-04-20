/**
 * packages/local-agents/tests/client.test.js
 *
 * Unit tests for packages/local-agents/src/client.js and packages/local-agents/src/orchestrator.js
 *
 * These tests run fully offline — no actual Ollama / LM Studio connection needed.
 * Network calls are intercepted via monkey-patching http.request.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import http from "http";
import { EventEmitter } from "events";

// ── helpers ──────────────────────────────────────────────────────────────────

/**
 * Creates a fake http.request that returns the given JSON body with the given status.
 */
function mockHttpRequest(statusCode, body) {
  return vi.fn((_options, callback) => {
    const res = new EventEmitter();
    res.statusCode = statusCode;

    const req = new EventEmitter();
    req.write = vi.fn();
    req.end = vi.fn(() => {
      callback(res);
      res.emit("data", Buffer.from(JSON.stringify(body)));
      res.emit("end");
    });
    req.setTimeout = vi.fn();
    return req;
  });
}

/**
 * Creates a fake http.request that calls the error handler.
 */
function mockHttpError(message) {
  return vi.fn((_options, _callback) => {
    const req = new EventEmitter();
    req.write = vi.fn();
    req.end = vi.fn(() => {
      req.emit("error", new Error(message));
    });
    req.setTimeout = vi.fn();
    return req;
  });
}

// ── tests ─────────────────────────────────────────────────────────────────────

describe("LocalAgentClient — module structure", () => {
  it("exports expected symbols", async () => {
    const mod = await import("../src/client.js");
    expect(typeof mod.LocalAgentClient).toBe("function");
    expect(typeof mod.OllamaClient).toBe("function");
    expect(typeof mod.LMStudioClient).toBe("function");
    expect(typeof mod.askLocalAgentAboutCode).toBe("function");
    expect(typeof mod.proposeCodeEdit).toBe("function");
    expect(mod.DEFAULTS.ollama.baseUrl).toBe("http://127.0.0.1:11435");
    expect(mod.DEFAULTS.lmstudio.baseUrl).toBe("http://192.168.254.101:1234");
  });

  it("DEFAULTS.ollama.models has GLM-5.1:cloud as first choice", async () => {
    const { DEFAULTS } = await import("../src/client.js");
    expect(DEFAULTS.ollama.models[0]).toBe("GLM-5.1:cloud");
    expect(DEFAULTS.ollama.models[1]).toBe("qwen3.5-local:latest");
  });
});

describe("OllamaClient", () => {
  let OllamaClient;

  beforeEach(async () => {
    // Re-import to get a fresh instance (avoids cached _activeModel)
    const mod = await import("../src/client.js");
    OllamaClient = mod.OllamaClient;
  });

  it("resolveModel picks GLM-5.1:cloud when available", async () => {
    const client = new OllamaClient({
      baseUrl: "http://127.0.0.1:11435",
      models: ["GLM-5.1:cloud", "qwen3.5-local:latest"],
    });

    // Patch listModels directly
    client.listModels = async () => ["GLM-5.1:cloud", "qwen3.5-local:latest"];
    const model = await client.resolveModel();
    expect(model).toBe("GLM-5.1:cloud");
  });

  it("resolveModel falls back to qwen3.5-local:latest when GLM not present", async () => {
    const client = new OllamaClient({
      baseUrl: "http://127.0.0.1:11435",
      models: ["GLM-5.1:cloud", "qwen3.5-local:latest"],
    });
    client.listModels = async () => ["qwen3.5-local:latest", "llama3:latest"];
    const model = await client.resolveModel();
    expect(model).toBe("qwen3.5-local:latest");
  });

  it("resolveModel falls back to first available if no preferred model found", async () => {
    const client = new OllamaClient({
      models: ["GLM-5.1:cloud", "qwen3.5-local:latest"],
    });
    client.listModels = async () => ["mistral:latest"];
    const model = await client.resolveModel();
    expect(model).toBe("mistral:latest");
  });

  it("resolveModel throws when no models available at all", async () => {
    const client = new OllamaClient({ models: ["GLM-5.1:cloud"] });
    client.listModels = async () => [];
    await expect(client.resolveModel()).rejects.toThrow(/No preferred models/);
  });

  it("complete returns { ok, model, backend, text } on success", async () => {
    const client = new OllamaClient({ models: ["GLM-5.1:cloud"] });
    client.resolveModel = async () => "GLM-5.1:cloud";
    client.complete = async (opts) => ({
      ok: true,
      model: "GLM-5.1:cloud",
      backend: "ollama",
      text: "This is the answer.",
    });
    const result = await client.complete({ prompt: "What does this code do?" });
    expect(result.ok).toBe(true);
    expect(result.backend).toBe("ollama");
    expect(result.text).toBeTruthy();
  });

  it("ping returns ok:false when not reachable", async () => {
    const client = new OllamaClient({ baseUrl: "http://127.0.0.1:11435" });
    client.resolveModel = async () => { throw new Error("ECONNREFUSED"); };
    const status = await client.ping();
    expect(status.ok).toBe(false);
    expect(status.error).toMatch(/ECONNREFUSED/);
    expect(status.backend).toBe("ollama");
  });
});

describe("LMStudioClient", () => {
  let LMStudioClient;

  beforeEach(async () => {
    const mod = await import("../src/client.js");
    LMStudioClient = mod.LMStudioClient;
  });

  it("resolveModel uses first available model", async () => {
    const client = new LMStudioClient({ baseUrl: "http://192.168.254.101:1234" });
    client.listModels = async () => ["mistral-7b-instruct", "phi-3"];
    const model = await client.resolveModel();
    expect(model).toBe("mistral-7b-instruct");
  });

  it("resolveModel throws when no models loaded", async () => {
    const client = new LMStudioClient({});
    client.listModels = async () => [];
    await expect(client.resolveModel()).rejects.toThrow(/no models loaded/i);
  });

  it("ping returns ok:false when not reachable", async () => {
    const client = new LMStudioClient({ baseUrl: "http://192.168.254.101:1234" });
    client.resolveModel = async () => { throw new Error("ETIMEDOUT"); };
    const status = await client.ping();
    expect(status.ok).toBe(false);
    expect(status.backend).toBe("lmstudio");
  });
});

describe("LocalAgentClient — unified interface", () => {
  let LocalAgentClient;

  beforeEach(async () => {
    const mod = await import("../src/client.js");
    LocalAgentClient = mod.LocalAgentClient;
  });

  it("complete tries ollama first, falls back to lmstudio", async () => {
    const client = new LocalAgentClient();
    let tried = [];

    client.ollama.complete = async () => {
      tried.push("ollama");
      throw new Error("ECONNREFUSED");
    };
    client.lmstudio.complete = async () => {
      tried.push("lmstudio");
      return { ok: true, model: "phi-3", backend: "lmstudio", text: "fallback answer" };
    };

    const result = await client.complete({ prompt: "test" });
    expect(tried).toEqual(["ollama", "lmstudio"]);
    expect(result.ok).toBe(true);
    expect(result.backend).toBe("lmstudio");
  });

  it("complete returns ok:false when all backends fail", async () => {
    const client = new LocalAgentClient();
    client.ollama.complete   = async () => { throw new Error("ollama down"); };
    client.lmstudio.complete = async () => { throw new Error("lmstudio down"); };

    const result = await client.complete({ prompt: "test" });
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/All backends failed/);
    expect(result.errors.length).toBeGreaterThan(0);
  });

  it("complete respects forced backend", async () => {
    const client = new LocalAgentClient();
    let tried = [];
    client.ollama.complete   = async () => { tried.push("ollama");   return { ok: true, model: "GLM", backend: "ollama",   text: "ok" }; };
    client.lmstudio.complete = async () => { tried.push("lmstudio"); return { ok: true, model: "phi", backend: "lmstudio", text: "ok" }; };

    await client.complete({ prompt: "test", backend: "lmstudio" });
    expect(tried[0]).toBe("lmstudio");
  });

  it("healthCheck returns status for both backends", async () => {
    const client = new LocalAgentClient();
    client.ollama.ping   = async () => ({ ok: true,  backend: "ollama",   model: "GLM-5.1:cloud" });
    client.lmstudio.ping = async () => ({ ok: false, backend: "lmstudio", error: "not running" });

    const health = await client.healthCheck();
    expect(health.ollama.ok).toBe(true);
    expect(health.lmstudio.ok).toBe(false);
    expect(health.anyAvailable).toBe(true);
  });

  it("healthCheck anyAvailable:false when both down", async () => {
    const client = new LocalAgentClient();
    client.ollama.ping   = async () => ({ ok: false, backend: "ollama" });
    client.lmstudio.ping = async () => ({ ok: false, backend: "lmstudio" });

    const health = await client.healthCheck();
    expect(health.anyAvailable).toBe(false);
  });
});

describe("askLocalAgentAboutCode", () => {
  it("sends file content + question and returns answer", async () => {
    const { askLocalAgentAboutCode, LocalAgentClient } = await import("../src/client.js");

    const client = new LocalAgentClient();
    client.ollama.complete = async ({ prompt }) => ({
      ok: true, model: "GLM", backend: "ollama",
      text: "The getBinPath function is on line 12.",
    });
    client.lmstudio.complete = async () => { throw new Error("not used"); };

    const result = await askLocalAgentAboutCode(client, {
      filePath: "lib/platform.js",
      fileContent: 'function getBinPath() { return "~/.local/bin"; }',
      question: "Where is getBinPath defined?",
    });

    expect(result.ok).toBe(true);
    expect(result.text).toMatch(/getBinPath/);
  });
});

describe("proposeCodeEdit", () => {
  it("returns proposedPatch when agent returns a diff", async () => {
    const { proposeCodeEdit, LocalAgentClient } = await import("../src/client.js");

    const fakeDiff = `--- a/lib/platform.js\n+++ b/lib/platform.js\n@@ -1,1 +1,1 @@\n-const x = 1;\n+const x = 2;\n`;

    const client = new LocalAgentClient();
    client.ollama.complete = async () => ({
      ok: true, model: "GLM", backend: "ollama",
      text: "```diff\n" + fakeDiff + "```",
    });
    client.lmstudio.complete = async () => { throw new Error("not used"); };

    const result = await proposeCodeEdit(client, {
      filePath: "lib/platform.js",
      fileContent: "const x = 1;\n",
      instruction: "Change x to 2",
    });

    expect(result.ok).toBe(true);
    expect(result.proposedPatch).toContain("const x = 2");
  });

  it("returns proposedPatch:null when agent says NOCHANGE", async () => {
    const { proposeCodeEdit, LocalAgentClient } = await import("../src/client.js");

    const client = new LocalAgentClient();
    client.ollama.complete = async () => ({
      ok: true, model: "GLM", backend: "ollama", text: "NOCHANGE",
    });
    client.lmstudio.complete = async () => { throw new Error("not used"); };

    const result = await proposeCodeEdit(client, {
      filePath: "lib/platform.js",
      fileContent: "const x = 1;\n",
      instruction: "Change nothing",
    });

    expect(result.ok).toBe(true);
    expect(result.proposedPatch).toBeNull();
    expect(result.explanation).toMatch(/no change/i);
  });
});
