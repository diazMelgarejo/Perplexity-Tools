import path from "path";
import { fileURLToPath } from "url";
/**
 * True when `importMetaUrl` is the Node entry module for `entryArgv`.
 * Resolves relative argv paths against cwd (e.g. `build/index.js`, `packages/.../index.js`).
 */
export function isDirectExecution(importMetaUrl, entryArgv) {
    if (!entryArgv)
        return false;
    return fileURLToPath(importMetaUrl) === path.resolve(entryArgv);
}
