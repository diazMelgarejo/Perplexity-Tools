# scripts/ensure_requirements.ps1 — Windows requirements probe + installer
# Perpetua-Tools v0.9.9.8 — Run on Windows GPU box (PowerShell 5.1+)
#
# Checks / installs:
#   LM Studio (winget install if missing)
#   Python venv + pip deps (sha256-stamped)
#   Node 20+ (winget install if missing) + alphaclaw package deps
#
# Usage:
#   .\scripts\ensure_requirements.ps1            # check + install
#   .\scripts\ensure_requirements.ps1 -CheckOnly # probe only
#   .\scripts\ensure_requirements.ps1 -Force     # reinstall everything
#   .\scripts\ensure_requirements.ps1 -Quiet     # suppress INFO lines
#
# Env overrides:
#   LM_STUDIO_WIN_PORT — override default 1234

param(
    [switch]$CheckOnly,
    [switch]$Force,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$LmPort   = $env:LM_STUDIO_WIN_PORT ?? "1234"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$LogDir   = Join-Path $RepoRoot ".logs"
$HardFail = $false

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log($Level, $Msg) {
    $ts   = (Get-Date).ToString("HH:mm:ss")
    $line = "[$ts] $Level [pt-win] $Msg"
    if ($Level -ne "INFO " -or -not $Quiet) { Write-Host $line }
    Add-Content -Path (Join-Path $LogDir "ensure-win.log") -Value $line -ErrorAction SilentlyContinue
}
function ok($m)   { Write-Log "OK   " $m }
function info($m) { Write-Log "INFO " $m }
function warn($m) { Write-Log "WARN " $m }
function err($m)  { Write-Log "ERROR" $m; $script:HardFail = $true }

$WinVer = (Get-CimInstance Win32_OperatingSystem).Caption
info "Platform: $WinVer"

# ── PHASE 1: LM Studio ────────────────────────────────────────────────────────
info "Phase 1 — LM Studio"

$LmExe = @(
    "$env:LOCALAPPDATA\Programs\LM-Studio\LM Studio.exe",
    "$env:PROGRAMFILES\LM-Studio\LM Studio.exe",
    "$env:LOCALAPPDATA\LM-Studio\LM Studio.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $LmExe) {
    if ($CheckOnly) {
        err "LM Studio not installed. Run without -CheckOnly to install via winget."
    } else {
        info "Installing LM Studio via winget..."
        try {
            winget install --id "ElementLabs.LMStudio" `
                --accept-source-agreements --accept-package-agreements --silent `
                2>&1 | Tee-Object -Append (Join-Path $LogDir "lmstudio-install.log")
            $LmExe = @(
                "$env:LOCALAPPDATA\Programs\LM-Studio\LM Studio.exe",
                "$env:PROGRAMFILES\LM-Studio\LM Studio.exe"
            ) | Where-Object { Test-Path $_ } | Select-Object -First 1
            if ($LmExe) { ok "LM Studio installed: $LmExe" }
            else { err "winget completed but LM Studio binary not found — check logs" }
        } catch {
            err "winget failed: $_. Manual: https://lmstudio.ai/download"
        }
    }
} else {
    ok "LM Studio: $LmExe"
}

# ── PHASE 2: LM Studio server ─────────────────────────────────────────────────
info "Phase 2 — LM Studio server probe (:$LmPort)"

if (-not $HardFail) {
    try {
        Invoke-RestMethod -Uri "http://localhost:${LmPort}/v1/models" -TimeoutSec 5 -ErrorAction Stop | Out-Null
        ok "LM Studio server responding on :$LmPort"
    } catch {
        warn "LM Studio server not reachable on :$LmPort"
        warn "Open LM Studio → Local Server tab → Start Server → load Qwen3.5-27B model"
    }
}

# ── PHASE 3: Node 20+ ─────────────────────────────────────────────────────────
info "Phase 3 — Node.js 20+"

$NodeOk = $false
try {
    $NodeVer = (node --version 2>$null).TrimStart("v")
    $NodeMajor = [int]($NodeVer -split "\.")[0]
    if ($NodeMajor -ge 20) { ok "Node.js v$NodeMajor present"; $NodeOk = $true }
    else { warn "Node.js v$NodeMajor found — Node 20+ required" }
} catch {
    if ($CheckOnly) {
        warn "Node.js not found — run without -CheckOnly to install via winget"
    } else {
        info "Installing Node.js LTS via winget..."
        try {
            winget install --id "OpenJS.NodeJS.LTS" `
                --accept-source-agreements --accept-package-agreements --silent `
                2>&1 | Tee-Object -Append (Join-Path $LogDir "node-install.log")
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
            $NodeOk = $true
            ok "Node.js installed"
        } catch {
            warn "Node.js install failed: $_. Manual: https://nodejs.org"
        }
    }
}

# ── PHASE 4: Node packages ────────────────────────────────────────────────────
info "Phase 4 — Node packages"

if ($NodeOk) {
    $Packages = @("packages\alphaclaw-adapter", "packages\alphaclaw-mcp")
    foreach ($pkg in $Packages) {
        $PkgDir = Join-Path $RepoRoot $pkg
        if (-not (Test-Path $PkgDir)) { info "$pkg`: not found — skipping"; continue }
        $PkgJson = Join-Path $PkgDir "package.json"
        if (-not (Test-Path $PkgJson)) { info "$pkg`: no package.json — skipping"; continue }

        $NodeMod  = Join-Path $PkgDir "node_modules"
        $Stamp    = Join-Path $PkgDir ".node_stamp"
        $PkgHash  = (Get-FileHash $PkgJson -Algorithm SHA256).Hash
        $StampVal = if (Test-Path $Stamp) { Get-Content $Stamp } else { "" }

        if (-not (Test-Path $NodeMod) -or $Force -or $StampVal -ne $PkgHash) {
            if (-not $CheckOnly) {
                info "$pkg`: npm install..."
                Push-Location $PkgDir
                try {
                    npm install --silent 2>&1 | Out-File -Append (Join-Path $LogDir "install.log")
                    Set-Content $Stamp $PkgHash
                    ok "$pkg`: Node deps installed"
                } catch { warn "$pkg`: npm install failed" } finally { Pop-Location }
            } else {
                if (-not (Test-Path $NodeMod)) { warn "$pkg\node_modules missing" }
                else { warn "$pkg`: package.json changed — run without -CheckOnly" }
            }
        } else {
            ok "$pkg`: up-to-date"
        }
    }
}

# ── PHASE 5: Python venv ──────────────────────────────────────────────────────
info "Phase 5 — Python venv + deps"

$VenvDir   = Join-Path $RepoRoot ".venv"
$ReqFile   = Join-Path $RepoRoot "requirements.txt"
$StampFile = Join-Path $RepoRoot ".requirements.stamp"
$VenvFresh = $false

if (-not (Test-Path $VenvDir)) {
    if (-not $CheckOnly) {
        info "Creating Python venv..."
        python -m venv $VenvDir 2>&1 | Out-File -Append (Join-Path $LogDir "install.log")
        $VenvFresh = $true
    } else { warn ".venv not found — run without -CheckOnly" }
}

if (Test-Path $VenvDir) {
    $PipExe  = Join-Path $VenvDir "Scripts\pip.exe"
    $ReqHash = (Get-FileHash $ReqFile -Algorithm SHA256).Hash
    $StampHash = if (Test-Path $StampFile) {
        (Get-Content $StampFile | Where-Object { $_ -match "^python_req=" }) -replace "python_req=",""
    } else { "" }

    if ($Force -or $VenvFresh -or $StampHash -ne $ReqHash) {
        if (-not $CheckOnly) {
            info "Installing Python deps..."
            & $PipExe install -q -r $ReqFile 2>&1 | Out-File -Append (Join-Path $LogDir "install.log")
            "python_req=$ReqHash`nts=$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ssZ')`nversion=1" | Set-Content $StampFile
            ok "Python deps installed"
        } else { warn "requirements.txt changed — run without -CheckOnly" }
    } else { ok "Python deps up-to-date" }
}

# ── RESULT ────────────────────────────────────────────────────────────────────
Write-Host ""
if ($HardFail) {
    err "Hard requirements FAILED — see output above. Spec: CLAUDE-instru.md §6"
    Write-Host ""; exit 1
} else {
    ok "Perpetua-Tools Windows requirements check complete"
    Write-Host ""; exit 0
}
