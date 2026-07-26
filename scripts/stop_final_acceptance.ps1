# InsightFlow Agent V2-08 Final Acceptance Environment Stop Script
# Purpose: Stop all acceptance environment processes using saved PIDs with process-tree kill
# Verifies port release and log file cleanup. Idempotent and safe.

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$Runtime = Join-Path $Root ".runtime\final-acceptance"
$PidDir = Join-Path $Runtime "pids"
$LogsDir = Join-Path $Runtime "logs"

Write-Host "=== Stopping Final Acceptance Environment ===" -ForegroundColor Yellow
Write-Host ""

if (-not (Test-Path $PidDir)) {
    Write-Host "No PID directory found. Nothing to stop." -ForegroundColor Gray
    exit 0
}

# ============================================================
# Helper: kill process tree by PID using taskkill /T /F
# ============================================================
function Stop-ProcessTree {
    param([int]$ProcId, [string]$Label)
    try {
        $prevEAP = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        $null = & taskkill /PID $ProcId /T /F 2>&1
        $ErrorActionPreference = $prevEAP
        Start-Sleep -Milliseconds 800
        $alive = Get-Process -Id $ProcId -ErrorAction SilentlyContinue
        if ($alive) {
            Stop-Process -Id $ProcId -Force -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 500
            $alive = Get-Process -Id $ProcId -ErrorAction SilentlyContinue
        }
        if (-not $alive) {
            Write-Host "[OK] $Label stopped (PID: $ProcId)" -ForegroundColor Green
            return $true
        } else {
            Write-Host "[WARN] $Label may still be running (PID: $ProcId)" -ForegroundColor Yellow
            return $false
        }
    } catch {
        Write-Host "[WARN] Error stopping $Label (PID: $ProcId)" -ForegroundColor Yellow
        return $false
    }
}

# ============================================================
# 1. Stop all tracked processes by PID with process-tree kill
# ============================================================
$allPidFile = Join-Path $PidDir "acceptance-processes.pid"
if (Test-Path -LiteralPath $allPidFile) {
    $allPids = @(
        Get-Content -LiteralPath $allPidFile |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -match '^\d+$' } |
            Select-Object -Unique
    )
    foreach ($savedPid in $allPids) {
        if (Get-Process -Id $savedPid -ErrorAction SilentlyContinue) {
            [void](Stop-ProcessTree -ProcId $savedPid -Label "Acceptance child process")
        }
    }
    Remove-Item -LiteralPath $allPidFile -Force -ErrorAction SilentlyContinue
}

$pidSpecs = @(
    @{File="backend.pid";  Name="FastAPI backend"},
    @{File="worker.pid";   Name="Task worker"},
    @{File="frontend.pid"; Name="Frontend (Vite)"}
)

$stopped = 0; $alreadyGone = 0
foreach ($spec in $pidSpecs) {
    $pidFile = Join-Path $PidDir $spec.File
    if (-not (Test-Path $pidFile)) {
        Write-Host "[SKIP] No PID file for $($spec.Name)" -ForegroundColor Gray
        continue
    }
    $savedPid = (Get-Content -Path $pidFile -Raw).Trim()
    if (-not $savedPid) {
        Remove-Item -Path $pidFile -Force -ErrorAction SilentlyContinue
        continue
    }
    $exists = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
    if (-not $exists) {
        Write-Host "[OK] $($spec.Name) (PID: $savedPid) already stopped" -ForegroundColor Gray
        $alreadyGone++
        Remove-Item -Path $pidFile -Force -ErrorAction SilentlyContinue
        continue
    }
    if (Stop-ProcessTree -ProcId $savedPid -Label $spec.Name) {
        $stopped++
    }
    Remove-Item -Path $pidFile -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "Stopped: $stopped | Already gone: $alreadyGone" -ForegroundColor Cyan

# ============================================================
# 2. Verify ports 8000 and 5173 are released
# ============================================================
Write-Host ""
Write-Host "[...] Verifying port release..." -ForegroundColor Yellow

function Test-PortFree {
    param([int]$Port)
    # Use netstat (fast and reliable) instead of Get-NetTCPConnection
    $line = & netstat -ano 2>&1 | Select-String "LISTENING" | Select-String ":$Port "
    return ($null -eq $line)
}

$portsToCheck = @(8000, 5173)
$maxWait = 10
foreach ($port in $portsToCheck) {
    $free = $false
    for ($i = 0; $i -lt $maxWait; $i++) {
        if (Test-PortFree -Port $port) {
            Write-Host "[OK] Port $port released" -ForegroundColor Green
            $free = $true
            break
        }
        Start-Sleep -Seconds 1
    }
    if (-not $free) {
        Write-Host "[WARN] Port $port still in use after ${maxWait}s" -ForegroundColor Yellow
    }
}

# ============================================================
# 3. Verify log files can be deleted (no file locks)
# ============================================================
Write-Host ""
Write-Host "[...] Verifying log files are unlocked..." -ForegroundColor Yellow

$logFiles = @("backend.log", "backend-error.log", "worker.log", "worker-error.log", "frontend.log", "frontend-error.log")
$locked = @()
foreach ($lf in $logFiles) {
    $path = Join-Path $LogsDir $lf
    if (-not (Test-Path $path)) { continue }
    try {
        $fs = [System.IO.File]::Open($path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Delete)
        $fs.Close()
        $fs.Dispose()
        Write-Host "[OK] $lf is unlocked" -ForegroundColor Green
    } catch {
        Write-Host "[WARN] $lf is locked by another process" -ForegroundColor Yellow
        $locked += $lf
    }
}

if ($locked.Count -gt 0) {
    Write-Host ""
    Write-Host "Files still locked:" -ForegroundColor Yellow
    $locked | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    Write-Host "  (These will be cleaned on next reboot or after handle release)" -ForegroundColor DarkGray
} else {
    Write-Host "[OK] All log files unlocked" -ForegroundColor Green
}

Write-Host ""
Write-Host "Acceptance environment processes stopped." -ForegroundColor Cyan
Write-Host "Data preserved in .runtime\final-acceptance\" -ForegroundColor DarkGray
Write-Host "Clean: powershell -ExecutionPolicy Bypass -File `"$ScriptDir\clean_final_acceptance.ps1`"" -ForegroundColor Gray
