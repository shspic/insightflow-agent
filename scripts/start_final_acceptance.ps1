# InsightFlow Agent V2-08 Final Acceptance Environment Start Script
# Purpose: Start backend, worker, and frontend in a fully isolated directory
# Warning: Do NOT use this script in production to create default accounts

param(
    [switch]$SkipFrontend = $false
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$Runtime = Join-Path $Root ".runtime\final-acceptance"
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"
$PythonExe = Join-Path $BackendDir ".venv\Scripts\python.exe"

$DataDir = Join-Path $Runtime "data"
$LogsDir = Join-Path $Runtime "logs"
$PidDir = Join-Path $Runtime "pids"
$StorageUploads = Join-Path $Runtime "storage\uploads"
$StorageCharts = Join-Path $Runtime "storage\charts"
$StorageReports = Join-Path $Runtime "storage\reports"
$BackupsDir = Join-Path $Runtime "backups"
$DbPath = Join-Path $DataDir "acceptance.db"
$AcceptanceEnvPath = Join-Path $Runtime ".env.acceptance"
$LegacyCredPath = Join-Path $Runtime "temp-credentials.txt"
$TmpDir = Join-Path $Runtime "tmp"

$DbUrlPath = $DbPath.Replace('\', '/')

function ConvertTo-PlainText {
    param([Security.SecureString]$SecureValue)
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Read-AcceptanceAdminCredentials {
    while ($true) {
        $username = (Read-Host "管理员用户名").Trim().ToLowerInvariant()
        if ($username -match '^[A-Za-z0-9_.-]{3,50}$') {
            break
        }
        Write-Host "[FAIL] 管理员用户名需为 3 至 50 位字母、数字、点、下划线或连字符，请重新输入。" -ForegroundColor Red
    }

    while ($true) {
        $securePassword = Read-Host "管理员密码" -AsSecureString
        $securePasswordConfirm = Read-Host "确认管理员密码" -AsSecureString
        $password = $null
        $passwordConfirm = $null
        try {
            $password = ConvertTo-PlainText -SecureValue $securePassword
            $passwordConfirm = ConvertTo-PlainText -SecureValue $securePasswordConfirm
            if ($password -cne $passwordConfirm) {
                Write-Host "[FAIL] 两次输入的管理员密码不一致，请重新输入。" -ForegroundColor Red
                continue
            }
            if ($password.Length -lt 10 -or $password.Length -gt 256) {
                Write-Host "[FAIL] 当前隔离环境的管理员密码长度必须为 10 至 256 位，请重新输入。" -ForegroundColor Red
                continue
            }
            return @{ Username = $username; Password = $password }
        } finally {
            $passwordConfirm = $null
            if ($securePassword) { $securePassword.Dispose() }
            if ($securePasswordConfirm) { $securePasswordConfirm.Dispose() }
        }
    }
}

Write-Host "=== InsightFlow Agent V2-08 Final Acceptance Environment ===" -ForegroundColor Cyan
Write-Host ""

$adminCredentials = Read-AcceptanceAdminCredentials
$AdminUsername = $adminCredentials.Username
$AdminPassword = $adminCredentials.Password
$adminCredentials = $null

# ============================================================
# 1. Create isolated directories
# ============================================================
$dirs = @($DataDir, $LogsDir, $PidDir, $TmpDir, $StorageUploads, $StorageCharts, $StorageReports, $BackupsDir)
foreach ($d in $dirs) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}
Write-Host "[OK] Isolated directories created: $Runtime" -ForegroundColor Green
if (Test-Path -LiteralPath $LegacyCredPath) {
    Remove-Item -LiteralPath $LegacyCredPath -Force
    Write-Host "[OK] 已删除旧版明文凭据文件：$LegacyCredPath" -ForegroundColor Green
}

# ============================================================
# 2. Load or create the isolated auth secret
# ============================================================
if (Test-Path -LiteralPath $AcceptanceEnvPath) {
    $acceptanceEnvContent = (Get-Content -LiteralPath $AcceptanceEnvPath -Raw -Encoding ASCII).Trim()
    if ($acceptanceEnvContent -notmatch '\AAUTH_SECRET_KEY=([A-Za-z0-9+/]{64})\z') {
        Write-Host "[FAIL] 隔离配置文件格式无效，请先运行 clean_final_acceptance.ps1 后重试。" -ForegroundColor Red
        exit 1
    }
    $AuthSecret = $Matches[1]
    Write-Host "[OK] Reusing isolated AUTH_SECRET_KEY from ignored acceptance config" -ForegroundColor Green
} else {
    if (Test-Path -LiteralPath $DbPath) {
        Write-Host "[FAIL] 隔离数据库存在但隔离密钥配置缺失；为避免已有邀请码失效，请先运行 clean_final_acceptance.ps1。" -ForegroundColor Red
        exit 1
    }

    $AuthSecretBytes = New-Object 'byte[]' 48
    $AuthSecretGenerator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $AuthSecretGenerator.GetBytes($AuthSecretBytes)
        $AuthSecret = [Convert]::ToBase64String($AuthSecretBytes)
        Set-Content -LiteralPath $AcceptanceEnvPath -Value "AUTH_SECRET_KEY=$AuthSecret" -Encoding ASCII
    } finally {
        $AuthSecretGenerator.Dispose()
        [Array]::Clear($AuthSecretBytes, 0, $AuthSecretBytes.Length)
        $AuthSecretBytes = $null
    }
    Write-Host "[OK] New isolated AUTH_SECRET_KEY generated and saved in ignored acceptance config" -ForegroundColor Green
}

# ============================================================
# 3. Set environment variables
# ============================================================
$env:DATABASE_URL = "sqlite:///$DbUrlPath"
$env:ALEMBIC_DATABASE_URL = "sqlite:///$DbUrlPath"
$env:AUTH_SECRET_KEY = $AuthSecret
$env:UPLOAD_DIR = $StorageUploads
$env:CHART_DIR = $StorageCharts
$env:REPORT_DIR = $StorageReports
$env:BACKUP_DIR = $BackupsDir
$env:LLM_ENABLED = "false"
$env:ENABLE_LEGACY_V1_API = "false"
$env:AUTH_COOKIE_SECURE = "false"
$env:AUTH_COOKIE_SAMESITE = "lax"
$env:CORS_ORIGINS = "http://127.0.0.1:5173"
$env:PUBLIC_SITE_URL = "http://127.0.0.1:5173"
$env:DEBUG = "false"
$env:LOG_LEVEL = "INFO"
$env:ENV = "development"
$env:TESSERACT_CMD = ""
$env:DEEPSEEK_API_KEY = ""
$env:DEEPSEEK_MODEL = ""
$env:APP_NAME = "InsightFlow Agent Acceptance"
$env:LLM_PROVIDER = "deepseek"
$env:DEEPSEEK_API_BASE = "https://api.deepseek.com/v1"
$env:SQLITE_JOURNAL_MODE = "WAL"
$env:SQLITE_BUSY_TIMEOUT_MS = "30000"
$env:WORKER_POLL_INTERVAL_SECONDS = "2"
$env:WORKER_LEASE_SECONDS = "120"
$env:WORKER_HEARTBEAT_SECONDS = "15"
Write-Host "[OK] Environment variables set" -ForegroundColor Green
Write-Host "     DATABASE_URL = $env:DATABASE_URL" -ForegroundColor DarkGray
Write-Host "     ALEMBIC_DATABASE_URL = $env:ALEMBIC_DATABASE_URL" -ForegroundColor DarkGray

# ============================================================
# Helper: run a native command, capture exit code and output
# ============================================================
function Invoke-NativeCommand {
    param([string]$FilePath, [string[]]$ArgumentList, [string]$WorkingDirectory, [scriptblock]$OnOutput)
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $prevLoc = Get-Location
    try {
        if ($WorkingDirectory) { Set-Location $WorkingDirectory }
        $output = & $FilePath @ArgumentList 2>&1
        $ec = $LASTEXITCODE
        if ($OnOutput -and $output) { $output | ForEach-Object { & $OnOutput $_ } }
        return @{ ExitCode = $ec; Output = $output }
    } finally {
        $ErrorActionPreference = $prevEAP
        if ($WorkingDirectory) { Set-Location $prevLoc }
    }
}

function Invoke-PythonScript {
    param([string]$ScriptContent, [string]$Label = "check")
    $pyFile = Join-Path $TmpDir "${Label}.py"
    Set-Content -Path $pyFile -Value $ScriptContent -Encoding UTF8
    try { return Invoke-NativeCommand -FilePath $PythonExe -ArgumentList @($pyFile) -WorkingDirectory $BackendDir }
    finally { Remove-Item -Path $pyFile -Force -ErrorAction SilentlyContinue }
}

# ============================================================
# 4. Run Alembic migration
# ============================================================
Write-Host "[...] Running Alembic upgrade head..." -ForegroundColor Yellow
$result = Invoke-NativeCommand -FilePath $PythonExe -ArgumentList @("-m", "alembic", "upgrade", "head") -WorkingDirectory $BackendDir -OnOutput { Write-Host $_ }
if ($result.ExitCode -ne 0) {
    Write-Host "[FAIL] Alembic migration failed, exit code: $($result.ExitCode)" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Alembic migration completed" -ForegroundColor Green

# ============================================================
# 5. Verify migration tables in isolated database
# ============================================================
Write-Host "[...] Verifying isolated database..." -ForegroundColor Yellow
$checkPy = @'
import sqlite3, sys
db_path = r"{db_path}"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('alembic_version', 'users')")
tables = [row[0] for row in cursor.fetchall()]
if 'alembic_version' not in tables:
    print('MISSING: alembic_version', file=sys.stderr)
    sys.exit(1)
if 'users' not in tables:
    print('MISSING: users', file=sys.stderr)
    sys.exit(1)
cursor.execute('SELECT version_num FROM alembic_version')
rev = cursor.fetchone()[0]
print('REVISION=' + rev)
conn.close()
'@ -replace '\{db_path\}', $DbPath

$result = Invoke-PythonScript -ScriptContent $checkPy -Label "db_check"
if ($result.ExitCode -ne 0) {
    Write-Host "[FAIL] Database verification failed" -ForegroundColor Red
    Write-Host $result.Output -ForegroundColor DarkGray
    exit 1
}
$rev = ($result.Output | Select-String -Pattern 'REVISION=(.+)').Matches.Groups[1].Value
Write-Host "[OK] Isolated database verified: $DbPath" -ForegroundColor Green
Write-Host "     alembic_version: present | users: present | Revision: $rev" -ForegroundColor DarkGray

# ============================================================
# 6. Create or update acceptance admin
# ============================================================
Write-Host "[...] 正在创建或更新隔离验收管理员：$AdminUsername" -ForegroundColor Yellow
try {
    $env:ADMIN_PASSWORD = $AdminPassword
    $result = Invoke-NativeCommand -FilePath $PythonExe -ArgumentList @("-m", "app.cli.create_admin", "--username", $AdminUsername, "--update-password", "--yes") -WorkingDirectory $BackendDir -OnOutput { Write-Host $_ }
} finally {
    Remove-Item Env:ADMIN_PASSWORD -ErrorAction SilentlyContinue
}
if ($result.ExitCode -ne 0) {
    Write-Host "[FAIL] Admin creation failed, exit code: $($result.ExitCode)" -ForegroundColor Red
    exit 1
}

$adminCheckPy = @'
import os, sqlite3, sys
db_path = r"{db_path}"
username = os.environ["INSIGHTFLOW_ACCEPTANCE_ADMIN_USERNAME"]
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("SELECT username, role, status FROM users WHERE username=?", (username,))
row = cursor.fetchone()
if row is None:
    print('MISSING: requested admin', file=sys.stderr)
    sys.exit(1)
if row[1] != "admin" or row[2] != "active":
    print('INVALID_ADMIN_STATE|role=' + row[1] + '|status=' + row[2], file=sys.stderr)
    sys.exit(1)
print('USER_OK|username=' + row[0] + '|role=' + row[1] + '|status=' + row[2])
conn.close()
'@ -replace '\{db_path\}', $DbPath

try {
    $env:INSIGHTFLOW_ACCEPTANCE_ADMIN_USERNAME = $AdminUsername
    $result = Invoke-PythonScript -ScriptContent $adminCheckPy -Label "admin_check"
} finally {
    Remove-Item Env:INSIGHTFLOW_ACCEPTANCE_ADMIN_USERNAME -ErrorAction SilentlyContinue
}
if ($result.ExitCode -ne 0) {
    Write-Host "[FAIL] Admin verification failed" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Admin verified: $($result.Output -join ' ')" -ForegroundColor Green

# ============================================================
# 7. Check port availability
# ============================================================
$backendPort = 8000
$frontendPort = 5173
Write-Host "[...] Checking port availability..." -ForegroundColor Yellow

function Test-PortInUse { param([int]$Port)
    return ($null -ne (& netstat -ano 2>&1 | Select-String "LISTENING" | Select-String ":$Port "))
}
if (Test-PortInUse -Port $backendPort) { Write-Host "[FAIL] Port $backendPort is already in use" -ForegroundColor Red; exit 1 }
if (Test-PortInUse -Port $frontendPort) { Write-Host "[FAIL] Port $frontendPort is already in use" -ForegroundColor Red; exit 1 }
Write-Host "[OK] Ports $backendPort and $frontendPort are available" -ForegroundColor Green

# ============================================================
# Helper: Start background process, save PID
# ============================================================
function Start-BackgroundProcess {
    param([string]$FilePath, [string[]]$ArgumentList, [string]$WorkingDirectory, [string]$LogFile, [string]$ErrorLogFile, [string]$PidFile, [string]$Label)
    $proc = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput $LogFile -RedirectStandardError $ErrorLogFile
    $proc.Id | Set-Content -Path $PidFile -Encoding UTF8
    Write-Host "[OK] $Label started, PID: $($proc.Id)" -ForegroundColor Green
    return $proc.Id
}

# Windows PowerShell 5.1 在同时继承 PATH 与 Path 时，Start-Process 会因重复键失败。
$NormalizedProcessPath = $env:Path
[Environment]::SetEnvironmentVariable("PATH", $null, "Process")
[Environment]::SetEnvironmentVariable("Path", $null, "Process")
[Environment]::SetEnvironmentVariable("Path", $NormalizedProcessPath, "Process")

$AcceptanceProcessBaseline = @(
    Get-Process -Name python, node -ErrorAction SilentlyContinue | ForEach-Object { $_.Id }
)
$AcceptanceProcessPidFile = Join-Path $PidDir "acceptance-processes.pid"

function Update-AcceptanceProcessPidFile {
    Start-Sleep -Milliseconds 500
    @(
        Get-Process -Name python, node -ErrorAction SilentlyContinue |
            Where-Object { $AcceptanceProcessBaseline -notcontains $_.Id } |
            ForEach-Object { $_.Id }
    ) | Set-Content -Path $AcceptanceProcessPidFile -Encoding UTF8
}

# ============================================================
# 8. Start FastAPI backend
# ============================================================
Write-Host "[...] Starting FastAPI backend on port $backendPort..." -ForegroundColor Yellow
$backendLog = Join-Path $LogsDir "backend.log"
$backendPidFile = Join-Path $PidDir "backend.pid"
$backendPid = Start-BackgroundProcess -FilePath $PythonExe -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$backendPort", "--log-level", "info") -WorkingDirectory $BackendDir -LogFile $backendLog -ErrorLogFile (Join-Path $LogsDir "backend-error.log") -PidFile $backendPidFile -Label "FastAPI backend"
Update-AcceptanceProcessPidFile

# ============================================================
# 9. Start Worker
# ============================================================
Write-Host "[...] Starting task worker..." -ForegroundColor Yellow
$workerLog = Join-Path $LogsDir "worker.log"
$workerPidFile = Join-Path $PidDir "worker.pid"
$workerPid = Start-BackgroundProcess -FilePath $PythonExe -ArgumentList @("-m", "app.workers.task_worker") -WorkingDirectory $BackendDir -LogFile $workerLog -ErrorLogFile (Join-Path $LogsDir "worker-error.log") -PidFile $workerPidFile -Label "Task worker"
Update-AcceptanceProcessPidFile

# ============================================================
# 10. Start Frontend (Vite dev server with --strictPort)
# ============================================================
if (-not $SkipFrontend) {
    Write-Host "[...] Starting frontend on port $frontendPort (strictPort)..." -ForegroundColor Yellow
    $frontendLog = Join-Path $LogsDir "frontend.log"
    $frontendPidFile = Join-Path $PidDir "frontend.pid"
    if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
        Write-Host "[FAIL] node_modules not found in $FrontendDir" -ForegroundColor Red
        & "$ScriptDir\stop_final_acceptance.ps1"
        exit 1
    }
    $nodeExe = Get-Command node.exe -ErrorAction SilentlyContinue
    if (-not $nodeExe) { $nodeExe = Get-Command node -ErrorAction SilentlyContinue }
    if (-not $nodeExe) {
        Write-Host "[FAIL] node not found in PATH" -ForegroundColor Red
        & "$ScriptDir\stop_final_acceptance.ps1"
        exit 1
    }
    $viteJs = Join-Path $FrontendDir "node_modules\vite\bin\vite.js"
    if (-not (Test-Path $viteJs)) {
        Write-Host "[FAIL] vite.js not found: $viteJs" -ForegroundColor Red
        & "$ScriptDir\stop_final_acceptance.ps1"
        exit 1
    }
    $frontendPid = Start-BackgroundProcess -FilePath $nodeExe.Source -ArgumentList @($viteJs, "--host", "127.0.0.1", "--strictPort") -WorkingDirectory $FrontendDir -LogFile $frontendLog -ErrorLogFile (Join-Path $LogsDir "frontend-error.log") -PidFile $frontendPidFile -Label "Frontend (Vite)"
    Update-AcceptanceProcessPidFile
} else {
    Write-Host "[SKIP] Frontend skipped (-SkipFrontend)" -ForegroundColor Gray
}

# Backend, worker and frontend have inherited the secret. Do not retain it in
# the start script process for the remaining verification steps.
Remove-Item Env:AUTH_SECRET_KEY -ErrorAction SilentlyContinue
$AuthSecret = $null

# ============================================================
# 11. Wait for backend health check
# ============================================================
Write-Host "[...] Waiting for backend health check..." -ForegroundColor Yellow
$healthUrl = "http://127.0.0.1:${backendPort}/api/health"
$maxRetries = 30; $retryCount = 0; $backendReady = $false
do {
    $retryCount++
    try {
        $prevEAP = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        $resp = Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 2 -ErrorAction SilentlyContinue
        $ErrorActionPreference = $prevEAP
        if ($resp -and $resp.status -eq "ok") { $backendReady = $true }
    } catch {}
    if (-not $backendReady -and $retryCount -lt $maxRetries) { Start-Sleep -Seconds 2 }
} while (-not $backendReady -and $retryCount -lt $maxRetries)

if (-not $backendReady) {
    Write-Host "[FAIL] Backend did not become healthy within $($maxRetries * 2)s" -ForegroundColor Red
    if (Test-Path $backendLog) { Write-Host "--- backend log tail ---"; Get-Content -Path $backendLog -Tail 80 | ForEach-Object { Write-Host $_ } }
    & "$ScriptDir\stop_final_acceptance.ps1"
    exit 1
}
Write-Host "[OK] Backend health check passed" -ForegroundColor Green

# ============================================================
# 12. Wait for frontend
# ============================================================
if (-not $SkipFrontend) {
    Write-Host "[...] Waiting for frontend (port ${frontendPort})..." -ForegroundColor Yellow
    $maxRetries = 30; $retryCount = 0; $frontendReady = $false
    do {
        $retryCount++
        # Use curl.exe (reliable on Windows 10+)
        try {
            $prevEAP = $ErrorActionPreference; $ErrorActionPreference = "Continue"
            $curlOut = & curl.exe -s -o NUL -w "%{http_code}" "http://127.0.0.1:${frontendPort}" 2>&1
            $ErrorActionPreference = $prevEAP
            if ($LASTEXITCODE -eq 0 -and $curlOut -eq "200") {
                $frontendReady = $true
                Write-Host "[OK] Frontend HTTP 200 on 127.0.0.1:${frontendPort}" -ForegroundColor Green
                break
            }
        } catch {}
        # Fallback: Invoke-WebRequest
        try {
            $prevEAP = $ErrorActionPreference; $ErrorActionPreference = "Continue"
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:${frontendPort}" -Method Get -TimeoutSec 2 -UseBasicParsing -ErrorAction SilentlyContinue
            $ErrorActionPreference = $prevEAP
            if ($resp -and $resp.StatusCode -eq 200) {
                $frontendReady = $true
                Write-Host "[OK] Frontend accessible via Invoke-WebRequest" -ForegroundColor Green
                break
            }
        } catch {}
        if (-not $frontendReady -and $retryCount -lt $maxRetries) { Start-Sleep -Seconds 2 }
    } while (-not $frontendReady -and $retryCount -lt $maxRetries)
    if (-not $frontendReady) {
        Write-Host "[FAIL] Frontend not reachable on port ${frontendPort} after $($maxRetries * 2)s" -ForegroundColor Red
        Write-Host "Last 40 lines of frontend log:" -ForegroundColor Yellow
        if (Test-Path $frontendLog) { Get-Content -Path $frontendLog -Tail 40 | ForEach-Object { Write-Host $_ -ForegroundColor DarkGray } }
        Write-Host "--- frontend-error log:" -ForegroundColor Yellow
        $ferrLog = Join-Path $LogsDir "frontend-error.log"
        if (Test-Path $ferrLog) { Get-Content -Path $ferrLog -Tail 20 | ForEach-Object { Write-Host $_ -ForegroundColor DarkGray } }
        & "$ScriptDir\stop_final_acceptance.ps1"
        exit 1
    }
}

# ============================================================
# 13. Verify worker process is alive
# ============================================================
Start-Sleep -Seconds 2
$workerAlive = $false
try { if (Get-Process -Id $workerPid -ErrorAction SilentlyContinue) { $workerAlive = $true } } catch {}
if (-not $workerAlive) {
    Write-Host "[FAIL] Worker process died (PID: $workerPid)" -ForegroundColor Red
    if (Test-Path $workerLog) { Get-Content -Path $workerLog -Tail 40 | ForEach-Object { Write-Host $_ } }
    & "$ScriptDir\stop_final_acceptance.ps1"
    exit 1
}
Write-Host "[OK] Worker process running, PID: $workerPid" -ForegroundColor Green

# ============================================================
# 14. REAL admin login verification via Python requests.Session
# Full CSRF flow: GET /csrf -> POST /login -> GET /me
# Any 401/403 = FAIL
# ============================================================
Write-Host "[...] Verifying admin login (full CSRF flow)..." -ForegroundColor Yellow
$loginPy = @'
import json, os, sys, urllib.request, urllib.error, http.cookiejar

base = "http://127.0.0.1:8000"
username = os.environ["INSIGHTFLOW_ACCEPTANCE_ADMIN_USERNAME"]
password = os.environ["INSIGHTFLOW_ACCEPTANCE_ADMIN_PASSWORD"]

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

# Step 1: GET /api/v2/auth/csrf
try:
    req = urllib.request.Request(base + "/api/v2/auth/csrf", headers={"Origin": "http://127.0.0.1:5173"})
    resp = opener.open(req)
    csrf_data = json.loads(resp.read().decode())
    csrf_token = csrf_data["csrf_token"]
    print("STEP1_CSRF_OK: HTTP " + str(resp.status))
except Exception as e:
    print("STEP1_CSRF_FAIL: " + str(e))
    sys.exit(1)

# Step 2: POST /api/v2/auth/login with cookie + X-CSRF-Token header
try:
    login_body = json.dumps({"username": username, "password": password}).encode()
    req = urllib.request.Request(base + "/api/v2/auth/login", data=login_body, headers={
        "Content-Type": "application/json",
        "Origin": "http://127.0.0.1:5173",
        "X-CSRF-Token": csrf_token,
    })
    resp = opener.open(req)
    login_data = json.loads(resp.read().decode())
    if "user" not in login_data:
        print("STEP2_LOGIN_FAIL: no user in response")
        sys.exit(1)
    print("STEP2_LOGIN_OK: HTTP " + str(resp.status) + " user=" + login_data["user"]["username"] + " role=" + login_data["user"]["role"])
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print("STEP2_LOGIN_FAIL: HTTP " + str(e.code) + " " + body)
    sys.exit(1)
except Exception as e:
    print("STEP2_LOGIN_FAIL: " + str(e))
    sys.exit(1)

# Step 3: GET /api/v2/auth/me
try:
    req = urllib.request.Request(base + "/api/v2/auth/me")
    resp = opener.open(req)
    me_data = json.loads(resp.read().decode())
    if me_data["username"] != username:
        print("STEP3_ME_FAIL: wrong username=" + me_data.get("username"))
        sys.exit(1)
    if me_data["role"] != "admin":
        print("STEP3_ME_FAIL: wrong role=" + me_data.get("role"))
        sys.exit(1)
    if me_data["status"] != "active":
        print("STEP3_ME_FAIL: wrong status=" + me_data.get("status"))
        sys.exit(1)
    print("STEP3_ME_OK: HTTP " + str(resp.status) + " username=" + me_data["username"] + " role=" + me_data["role"] + " status=" + me_data["status"])
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print("STEP3_ME_FAIL: HTTP " + str(e.code) + " " + body)
    sys.exit(1)
except Exception as e:
    print("STEP3_ME_FAIL: " + str(e))
    sys.exit(1)

print("LOGIN_VERIFY_PASS")
sys.exit(0)
'@

try {
    $env:INSIGHTFLOW_ACCEPTANCE_ADMIN_USERNAME = $AdminUsername
    $env:INSIGHTFLOW_ACCEPTANCE_ADMIN_PASSWORD = $AdminPassword
    $result = Invoke-PythonScript -ScriptContent $loginPy -Label "login_verify"
} finally {
    Remove-Item Env:INSIGHTFLOW_ACCEPTANCE_ADMIN_USERNAME -ErrorAction SilentlyContinue
    Remove-Item Env:INSIGHTFLOW_ACCEPTANCE_ADMIN_PASSWORD -ErrorAction SilentlyContinue
    $AdminPassword = $null
    [GC]::Collect()
}
if ($result.ExitCode -ne 0) {
    Write-Host "[FAIL] Admin login verification FAILED" -ForegroundColor Red
    Write-Host "     This means the acceptance admin cannot log in." -ForegroundColor Red
    Write-Host "     Output:" -ForegroundColor DarkGray
    $result.Output | ForEach-Object { Write-Host "     $_" -ForegroundColor DarkGray }
    & "$ScriptDir\stop_final_acceptance.ps1"
    exit 1
}
Write-Host "[OK] Admin login verified: CSRF -> login -> /me all passed" -ForegroundColor Green

# ============================================================
# 15. Summary
# ============================================================
Write-Host ""
Write-Host "=== Acceptance Environment Started Successfully ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Login URL:      http://127.0.0.1:${frontendPort}" -ForegroundColor White
Write-Host "  Admin Username: $AdminUsername" -ForegroundColor White
Write-Host "  Admin Password: 已由用户输入，不显示、不保存" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Backend Log:    $backendLog" -ForegroundColor DarkGray
Write-Host "  Worker Log:     $workerLog" -ForegroundColor DarkGray
if (-not $SkipFrontend) { Write-Host "  Frontend Log:   $frontendLog" -ForegroundColor DarkGray }
Write-Host ""
Write-Host "  Stop:  powershell -ExecutionPolicy Bypass -File `"$ScriptDir\stop_final_acceptance.ps1`"" -ForegroundColor Gray
Write-Host "  Clean: powershell -ExecutionPolicy Bypass -File `"$ScriptDir\clean_final_acceptance.ps1`"" -ForegroundColor Gray
Write-Host ""
Write-Host "Invite Code: Log in as admin and create one via the admin panel." -ForegroundColor Gray
Write-Host ""
