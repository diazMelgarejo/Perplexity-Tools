
## [2026-04-21] Configuration Portability: OS-Agnostic Paths
- **Problem**: Absolute paths (e.g., /Users/user/...) in openclaw.json break cross-platform deployments (Linux/Windows/macOS).
- **Solution**: Always use ${HOME} variables in configuration templates. The AlphaClaw gateway and onboarding runtime MUST resolve these variables relative to the OS-specific home directory.
- **Action**: Enforce ${HOME} in all openclaw.json.template and active configuration files. Avoid hardcoding usernames or absolute paths.

## [2026-04-21] Core Policy: Additive Ghost Orchestration
- **Additive Configuration**: Never overwrite openclaw.json. Always read, deep-merge (via spread), and write back.
- **Upstream Autonomy**: PT and Orama act as ghost orchestrators. They absorb and extend OpenClaw/AlphaClaw features without becoming structural dependencies.
- **Non-Destructive Injection**: Use native onboarding hooks (like writeManagedImportOpenclawConfig) to inject PT/Orama configs.
- **Portability**: Always use ${HOME} variables for pathing to keep configurations OS-agnostic across Mac/Win/Linux.

## [2026-04-22] Symlink Portability & Validation
- **Requirement**: Git must track symlinks as Mode 120000. Use 'git ls-files -s' to verify.
- **Automation**: Startup scripts (start.sh) MUST validate symlinks. If a link is missing or broken, the script should attempt to recreate it or provide clear instructions on where the missing sibling dependency should live.
- **Agnostic Pathing**: Always use relative paths in symlinks (e.g., ../sibling) rather than absolute paths to ensure portability across different clones.
