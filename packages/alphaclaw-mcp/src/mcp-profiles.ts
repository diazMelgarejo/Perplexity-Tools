/**
 * Least-privilege MCP tool profiles (security fix 6, wired in fix 4).
 *
 * readonly (default): file/HTTP read tools only.
 * elevated: all 14 tools.
 * Opt-in flags re-enable process-spawn or mutating tools under readonly.
 */

const PROCESS_TOOLS = new Set(["alphaclaw_build_ui", "alphaclaw_run_tests"]);
const MUTATING_TOOLS = new Set(["alphaclaw_login", "local_agent_propose_edit"]);

function truthyEnv(name: string): boolean {
  const value = process.env[name];
  if (!value) return false;
  const normalized = value.trim().toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes";
}

function getProfile(): "readonly" | "elevated" {
  const raw = (process.env.ALPHACLAW_MCP_PROFILE || "readonly").trim().toLowerCase();
  return raw === "elevated" ? "elevated" : "readonly";
}

export function isToolAllowed(toolName: string): boolean {
  if (getProfile() === "elevated") return true;
  if (PROCESS_TOOLS.has(toolName)) {
    return truthyEnv("ALPHACLAW_MCP_ENABLE_PROCESS_TOOLS");
  }
  if (MUTATING_TOOLS.has(toolName)) {
    return truthyEnv("ALPHACLAW_MCP_ENABLE_MUTATING_TOOLS");
  }
  return true;
}

export function toolDisabledMessage(toolName: string): string {
  if (PROCESS_TOOLS.has(toolName)) {
    return (
      `Tool ${toolName} is disabled (readonly MCP profile). ` +
      "Set ALPHACLAW_MCP_ENABLE_PROCESS_TOOLS=1 or ALPHACLAW_MCP_PROFILE=elevated."
    );
  }
  if (MUTATING_TOOLS.has(toolName)) {
    return (
      `Tool ${toolName} is disabled (readonly MCP profile). ` +
      "Set ALPHACLAW_MCP_ENABLE_MUTATING_TOOLS=1 or ALPHACLAW_MCP_PROFILE=elevated."
    );
  }
  return `Tool ${toolName} is disabled for the current MCP profile.`;
}

export function profileStartupSummary(): string {
  const profile = getProfile();
  if (profile === "elevated") return "profile=elevated";
  const extras: string[] = [];
  if (truthyEnv("ALPHACLAW_MCP_ENABLE_PROCESS_TOOLS")) extras.push("process");
  if (truthyEnv("ALPHACLAW_MCP_ENABLE_MUTATING_TOOLS")) extras.push("mutating");
  return extras.length ? `profile=readonly+${extras.join("+")}` : "profile=readonly";
}
