#Requires -Version 5.1
<#
.SYNOPSIS
  Dev launcher - chay backend API + Celery worker (va tuy chon frontend) bang MOT lenh.

.DESCRIPTION
  Mo dong thoi trong CUNG mot cua so, log gop chung, moi dong gan nhan mau:
    [API]    FastAPI  (uvicorn --reload, cong 8000)
    [WORKER] Celery worker (queue: ingestion, sync) - xu ly ingest pending -> indexed
    [WEB]    Next.js dev (cong 3000) - chi khi dung -Frontend

  Nhan Ctrl+C de dung TAT CA (tu kill ca tien trinh con: uv -> python, npm -> node).

  Kien truc van tach API/worker nhu production; script nay chi la tien ich dev
  de khoi phai mo nhieu terminal.

.EXAMPLE
  .\dev.ps1
    Chay API + worker.

.EXAMPLE
  .\dev.ps1 -Frontend
    Chay API + worker + frontend.

.NOTES
  Neu bi chan boi Execution Policy, chay:
    powershell -ExecutionPolicy Bypass -File .\dev.ps1
  Hoac trong Claude Code go:  ! powershell -ExecutionPolicy Bypass -File .\dev.ps1
#>
param(
    [switch]$Frontend
)

$ErrorActionPreference = 'Stop'

# Thu muc chua script = goc repo
$RepoRoot    = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir  = Join-Path $RepoRoot 'backend'
$FrontendDir = Join-Path $RepoRoot 'frontend'

# --- Preflight ---------------------------------------------------------------
if (-not (Test-Path $BackendDir)) {
    Write-Host "Khong tim thay thu muc backend: $BackendDir" -ForegroundColor Red
    exit 1
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Khong tim thay 'uv' trong PATH. Cai dat: https://docs.astral.sh/uv/" -ForegroundColor Red
    exit 1
}
if ($Frontend -and -not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Host "Dung -Frontend nhung khong tim thay 'npm' trong PATH." -ForegroundColor Red
    exit 1
}

$script:Processes = New-Object System.Collections.ArrayList

# --- Khoi dong 1 dich vu qua cmd.exe /c (resolve uv/npm + redirect stdout) ----
function Start-DevService {
    param(
        [string]$Name,
        [System.ConsoleColor]$Color,
        [string]$Dir,
        [string]$CmdLine
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName               = $env:ComSpec
    $psi.Arguments              = "/c $CmdLine"
    $psi.WorkingDirectory       = $Dir
    $psi.UseShellExecute        = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError  = $true
    $psi.CreateNoWindow         = $true

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo           = $psi
    $proc.EnableRaisingEvents  = $true

    $ctx = [pscustomobject]@{ Name = $Name; Color = $Color }
    $handler = {
        if ($null -ne $EventArgs.Data) {
            $c = $Event.MessageData
            Write-Host ("[{0}] " -f $c.Name) -ForegroundColor $c.Color -NoNewline
            Write-Host $EventArgs.Data
        }
    }
    Register-ObjectEvent -InputObject $proc -EventName OutputDataReceived -Action $handler -MessageData $ctx | Out-Null
    Register-ObjectEvent -InputObject $proc -EventName ErrorDataReceived  -Action $handler -MessageData $ctx | Out-Null

    [void]$proc.Start()
    $proc.BeginOutputReadLine()
    $proc.BeginErrorReadLine()
    [void]$script:Processes.Add($proc)

    Write-Host ("  -> {0,-6} started (PID {1})" -f $Name, $proc.Id) -ForegroundColor $Color
}

# --- Don dep: kill ca cay tien trinh + go event -----------------------------
function Stop-All {
    Write-Host "`nDang dung tat ca dich vu..." -ForegroundColor Yellow
    foreach ($p in $script:Processes) {
        try {
            if (-not $p.HasExited) {
                # /T = kill ca tien trinh con, /F = force
                taskkill /PID $p.Id /T /F 2>$null | Out-Null
            }
        } catch { }
    }
    Get-EventSubscriber -ErrorAction SilentlyContinue | Unregister-Event -ErrorAction SilentlyContinue
    Write-Host "Da dung toan bo." -ForegroundColor Yellow
}

# --- Main --------------------------------------------------------------------
try {
    Write-Host ""
    Write-Host "=== Dev launcher - Enterprise Knowledge RAG ===" -ForegroundColor Cyan
    Write-Host "  API -> http://localhost:8000  (/docs, /health)" -ForegroundColor DarkGray
    if ($Frontend) { Write-Host "  WEB -> http://localhost:3000" -ForegroundColor DarkGray }
    Write-Host "  Nhan Ctrl+C de dung tat ca." -ForegroundColor DarkGray
    Write-Host ""

    Start-DevService -Name 'API' -Color Green -Dir $BackendDir -CmdLine 'uv run uvicorn app.main:app --reload --port 8000'
    Start-DevService -Name 'WORKER' -Color Magenta -Dir $BackendDir -CmdLine 'uv run celery -A app.workers.celery_app worker -Q ingestion,sync --loglevel=info --pool=solo'
    if ($Frontend) {
        Start-DevService -Name 'WEB' -Color Blue -Dir $FrontendDir -CmdLine 'npm run dev'
    }

    Write-Host ""

    # Vong cho: neu bat ky dich vu nao chet -> dung phan con lai
    while ($true) {
        Start-Sleep -Milliseconds 500
        foreach ($p in $script:Processes) {
            if ($p.HasExited) {
                Write-Host ("`nMot dich vu da thoat (PID {0}, exit code {1}). Dung phan con lai..." -f $p.Id, $p.ExitCode) -ForegroundColor Red
                return
            }
        }
    }
}
finally {
    Stop-All
}
