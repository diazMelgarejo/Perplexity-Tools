/**
 * Least-privilege MCP profiles (security fix 6).
 *
 * Default profile is readonly — process-spawning and session-mutating tools are
 * hidden from ListTools and rejected on CallTool unless elevated is enabled.
 *
 * Env (first match wins for profile name):
 *   ALPHACLAW_MCP_PROFILE=readonly|elevated
 *
 * Granular overrides (elevated if profile=elevated OR any flag is truthy):
 *   ALPHACLAW_MCP_ENABLE_PROCESS_TOOLS=1  — npm build + vitest subprocess tools
 *   ALPHACLAW_MCP_ENABLE_MUTATING_TOOLS=1 — login + local_agent_propose_edit
 */
export const READONLY_TOOL_NAMES = [
    "alphaclaw_health",
    "alphaclaw_status",
    "alphaclaw_watchdog_logs",
    "alphaclaw_read_config",
    "alphaclaw_list_providers",
    "alphaclaw_tail_logs",
    "alphaclaw_check_env",
    "local_agent_health",
    "local_agent_list_models",
    "local_agent_ask_about_code",
];
/** Requires elevated profile or ALPHACLAW_MCP_ENABLE_PROCESS_TOOLS=1 */
export const PROCESS_TOOL_NAMES = ["alphaclaw_build_ui", "alphaclaw_run_tests"];
/** Requires elevated profile or ALPHACLAW_MCP_ENABLE_MUTATING_TOOLS=1 */
export const MUTATING_TOOL_NAMES = ["alphaclaw_login", "local_agent_propose_edit"];
export const ELEVATED_ONLY_TOOL_NAMES = [
    ...PROCESS_TOOL_NAMES,
    ...MUTATING_TOOL_NAMES,
];
function truthyEnv(name) {
    const v = (process.env[name] ?? "").trim().toLowerCase();
    return v === "1" || v === "true" || v === "yes" || v === "on";
}
export function resolveMcpProfile() {
    const raw = (process.env.ALPHACLAW_MCP_PROFILE ?? "readonly").trim().toLowerCase();
    if (raw === "elevated" || raw === "full" || raw === "all")
        return "elevated";
    return "readonly";
}
export function processToolsEnabled() {
    return resolveMcpProfile() === "elevated" || truthyEnv("ALPHACLAW_MCP_ENABLE_PROCESS_TOOLS");
}
export function mutatingToolsEnabled() {
    return resolveMcpProfile() === "elevated" || truthyEnv("ALPHACLAW_MCP_ENABLE_MUTATING_TOOLS");
}
export function isToolAllowed(toolName) {
    if (READONLY_TOOL_NAMES.includes(toolName))
        return true;
    if (PROCESS_TOOL_NAMES.includes(toolName)) {
        return processToolsEnabled();
    }
    if (MUTATING_TOOL_NAMES.includes(toolName)) {
        return mutatingToolsEnabled();
    }
    return false;
}
export function toolDisabledMessage(toolName) {
    if (PROCESS_TOOL_NAMES.includes(toolName)) {
        return (`Tool "${toolName}" is disabled in readonly MCP profile. ` +
            `Set ALPHACLAW_MCP_PROFILE=elevated or ALPHACLAW_MCP_ENABLE_PROCESS_TOOLS=1.`);
    }
    if (MUTATING_TOOL_NAMES.includes(toolName)) {
        return (`Tool "${toolName}" is disabled in readonly MCP profile. ` +
            `Set ALPHACLAW_MCP_PROFILE=elevated or ALPHACLAW_MCP_ENABLE_MUTATING_TOOLS=1.`);
    }
    return `Tool "${toolName}" is not available in the current MCP profile.`;
}
export function profileStartupSummary() {
    const profile = resolveMcpProfile();
    const proc = processToolsEnabled();
    const mut = mutatingToolsEnabled();
    return (`profile=${profile} process_tools=${proc ? "on" : "off"} ` +
        `mutating_tools=${mut ? "on" : "off"}`);
}
