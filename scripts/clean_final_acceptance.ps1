# InsightFlow Agent V2-08 Final Acceptance Environment Clean Script
# Purpose: Safely delete the isolated acceptance environment with path safety checks
# Calls stop script first. Idempotent.

[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$Runtime = Join-Path $Root ".runtime\final-acceptance"
$RuntimeParent = Join-Path $Root ".runtime"

Write-Host "=== Cleaning Final Acceptance Environment ===" -ForegroundColor Yellow
Write-Host ""

function Test-PortFree {
    param([int]$Port)
    $line = & netstat -ano 2>&1 | Select-String "LISTENING" | Select-String ":$Port "
    return ($null -eq $line)
}

# ============================================================
# 1. Stop running processes first
# ============================================================
$stopScript = Join-Path $ScriptDir "stop_final_acceptance.ps1"
if (Test-Path $stopScript) {
    Write-Host "[...] Stopping running processes..." -ForegroundColor Yellow
    $prevEAP = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stopScript
    $stopExitCode = $LASTEXITCODE
    $ErrorActionPreference = $prevEAP
    if ($stopExitCode -ne 0) {
        Write-Host "[FAIL] 停止脚本执行失败，拒绝清理。" -ForegroundColor Red
        exit 1
    }
}

# ============================================================
# 2. Resolve and validate the exact target path
# ============================================================
$resolvedRoot = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Root).Path).TrimEnd('\', '/')
$expectedRuntime = [IO.Path]::GetFullPath((Join-Path $resolvedRoot ".runtime\final-acceptance")).TrimEnd('\', '/')
$requestedRuntime = [IO.Path]::GetFullPath($Runtime).TrimEnd('\', '/')
$rootPrefix = $resolvedRoot + [IO.Path]::DirectorySeparatorChar

if (-not $requestedRuntime.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    Write-Host "[FAIL] Safety: target is outside project root" -ForegroundColor Red
    Write-Host "  Target: $requestedRuntime" -ForegroundColor Red
    exit 1
}
if (-not $requestedRuntime.Equals($expectedRuntime, [StringComparison]::OrdinalIgnoreCase)) {
    Write-Host "[FAIL] Safety: target is not the exact final-acceptance directory" -ForegroundColor Red
    Write-Host "  Target: $requestedRuntime" -ForegroundColor Red
    exit 1
}

# ============================================================
# 3. Require stopped ports before any deletion
# ============================================================
$busyPorts = @()
foreach ($port in @(8000, 5173)) {
    if (-not (Test-PortFree -Port $port)) {
        $busyPorts += $port
    }
}
if ($busyPorts.Count -gt 0) {
    Write-Host "[FAIL] Safety: ports are still listening: $($busyPorts -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Ports 8000 and 5173 are not listening" -ForegroundColor Green

# ============================================================
# 4. Empty clean is a successful, verified no-op
# ============================================================
if (-not (Test-Path -LiteralPath $requestedRuntime)) {
    Write-Host "Acceptance environment directory does not exist: $requestedRuntime" -ForegroundColor Gray
    Write-Host "[OK] Nothing to clean; PID files and isolated artifacts do not exist" -ForegroundColor Green
    exit 0
}

# ============================================================
# 5. Reject reparse points and enumerate exact entries
# ============================================================
$resolvedRuntime = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $requestedRuntime).Path).TrimEnd('\', '/')
if (-not $resolvedRuntime.Equals($expectedRuntime, [StringComparison]::OrdinalIgnoreCase)) {
    Write-Host "[FAIL] Safety: resolved target changed from the exact expected path" -ForegroundColor Red
    exit 1
}

$pathsToCheck = @($resolvedRoot)
if (Test-Path -LiteralPath $RuntimeParent) {
    $pathsToCheck += [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $RuntimeParent).Path).TrimEnd('\', '/')
}
$pathsToCheck += $resolvedRuntime
foreach ($pathToCheck in $pathsToCheck) {
    $item = Get-Item -LiteralPath $pathToCheck -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        Write-Host "[FAIL] Safety: reparse point is not allowed: $pathToCheck" -ForegroundColor Red
        exit 1
    }
}

$files = New-Object 'System.Collections.Generic.List[string]'
$directories = New-Object 'System.Collections.Generic.List[string]'
$pending = New-Object 'System.Collections.Generic.Stack[string]'
$pending.Push($resolvedRuntime)
$targetPrefix = $resolvedRuntime + [IO.Path]::DirectorySeparatorChar

while ($pending.Count -gt 0) {
    $directory = $pending.Pop()
    foreach ($entry in @(Get-ChildItem -LiteralPath $directory -Force)) {
        $entryPath = [IO.Path]::GetFullPath($entry.FullName)
        if (-not $entryPath.StartsWith($targetPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            Write-Host "[FAIL] Safety: child path escaped the exact target: $entryPath" -ForegroundColor Red
            exit 1
        }
        if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            Write-Host "[FAIL] Safety: reparse point is not allowed: $entryPath" -ForegroundColor Red
            exit 1
        }
        if ($entry.PSIsContainer) {
            $directories.Add($entryPath)
            $pending.Push($entryPath)
        } else {
            $files.Add($entryPath)
        }
    }
}

$pidFiles = @($files | Where-Object { [IO.Path]::GetExtension($_) -ieq ".pid" })
if ($pidFiles.Count -gt 0) {
    Write-Host "[FAIL] Safety: PID files remain after stop; refusing to delete." -ForegroundColor Red
    $pidFiles | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    exit 1
}
Write-Host "[OK] No PID files remain" -ForegroundColor Green

# ============================================================
# 6. Confirm the exact target
# ============================================================
Write-Host "About to delete:" -ForegroundColor Red
Write-Host "  $resolvedRuntime" -ForegroundColor White
Write-Host ""
Write-Host "This includes only the isolated database, uploads, reports, charts, backups, logs and config." -ForegroundColor DarkGray
Write-Host ""

if (-not $Force) {
    $confirmation = Read-Host "Type YES to confirm deletion"
    if ($confirmation -ne "YES") {
        Write-Host "Cancelled." -ForegroundColor Gray
        exit 0
    }
}

# ============================================================
# 7. Delete one validated literal path at a time, bottom-up
# ============================================================
foreach ($filePath in $files) {
    Remove-Item -LiteralPath $filePath -Force
}
foreach ($directoryPath in @($directories | Sort-Object { $_.Length } -Descending)) {
    Remove-Item -LiteralPath $directoryPath -Force
}
Remove-Item -LiteralPath $resolvedRuntime -Force

# ============================================================
# 8. Verify the requested postconditions
# ============================================================
if (Test-Path -LiteralPath $resolvedRuntime) {
    Write-Host "[FAIL] Acceptance environment still exists after cleanup" -ForegroundColor Red
    exit 1
}
foreach ($port in @(8000, 5173)) {
    if (-not (Test-PortFree -Port $port)) {
        Write-Host "[FAIL] Port $port started listening during cleanup verification" -ForegroundColor Red
        exit 1
    }
}

Write-Host "[OK] Acceptance environment fully cleaned" -ForegroundColor Green
Write-Host "    Deleted: $resolvedRuntime" -ForegroundColor DarkGray
Write-Host "[OK] Runtime directory, PID files, logs, database/WAL/SHM and isolated config are absent" -ForegroundColor Green
Write-Host "[OK] Ports 8000 and 5173 are not listening" -ForegroundColor Green

