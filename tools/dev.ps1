<#
.SYNOPSIS
  Windows (PowerShell) equivalent of the Makefile's developer commands.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\dev.ps1 setup    # first time: install, database, migrate, seed
  powershell -ExecutionPolicy Bypass -File tools\dev.ps1 dev      # API :8000 (new window) + web :5173

  Tasks: setup, install, db-up, db-down, migrate, seed, seed-perf, dev, dev-api, dev-web, check
  Needs: uv (Python), Node.js + pnpm, and Docker Desktop (for Postgres), all on PATH.
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet('help', 'setup', 'install', 'db-up', 'db-down', 'migrate', 'seed', 'seed-perf',
        'dev', 'dev-api', 'dev-web', 'check')]
    [string]$Task = 'help'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Api = Join-Path $Root 'apps\api'
$Web = Join-Path $Root 'apps\web'
$Compose = Join-Path $Root 'infra\compose\docker-compose.dev.yml'

function Require([string]$Command, [string]$Hint) {
    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
        Write-Host "'$Command' was not found on PATH. $Hint" -ForegroundColor Red
        exit 1
    }
}

# Run a native command in a folder and stop on failure.
function Run([string]$Dir, [string]$Exe, [string[]]$Arguments) {
    Push-Location $Dir
    try {
        & $Exe @Arguments
        if ($LASTEXITCODE -ne 0) { throw "$Exe $($Arguments -join ' ') failed (exit $LASTEXITCODE)" }
    }
    finally { Pop-Location }
}

function Install {
    Require 'uv' 'Install it: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
    Require 'pnpm' 'Install Node.js 20+ (https://nodejs.org), then run: npm install -g pnpm'
    Run $Api 'uv' @('sync')
    Run $Web 'pnpm' @('install')
}

function DbUp {
    Require 'docker' 'Install Docker Desktop and make sure it is running.'
    Run $Root 'docker' @('compose', '-f', $Compose, 'up', '-d', 'postgres')
    Write-Host 'Waiting for Postgres...'
    for ($i = 0; $i -lt 40; $i++) {
        & docker compose -f $Compose exec -T postgres pg_isready -U momentum *> $null
        if ($LASTEXITCODE -eq 0) { Write-Host 'Postgres is ready.'; return }
        Start-Sleep -Seconds 1
    }
    throw 'Postgres did not become ready. Check: docker compose -f infra\compose\docker-compose.dev.yml logs postgres'
}

switch ($Task) {
    'help' { Get-Help $PSCommandPath -Detailed | Out-Host }
    'install' { Install }
    'db-up' { DbUp }
    'db-down' { Run $Root 'docker' @('compose', '-f', $Compose, 'down') }
    'migrate' { Run $Api 'uv' @('run', 'momentum', 'migrate') }
    'seed' { Run $Api 'uv' @('run', 'momentum', 'seed') }
    'seed-perf' { Run $Api 'uv' @('run', 'momentum', 'seed', '--perf') }
    'setup' {
        Install
        DbUp
        Run $Api 'uv' @('run', 'momentum', 'migrate')
        Run $Api 'uv' @('run', 'momentum', 'seed')
        Write-Host "`nReady. Start the app with:  powershell -ExecutionPolicy Bypass -File tools\dev.ps1 dev" -ForegroundColor Green
    }
    'dev-api' { Run $Api 'uv' @('run', 'momentum', 'serve', '--reload', '--port', '8000') }
    'dev-web' { Run $Web 'pnpm' @('dev') }
    'dev' {
        # API in its own window (close it to stop), web here; open http://localhost:5173
        Start-Process powershell -WorkingDirectory $Api -ArgumentList @(
            '-NoExit', '-Command', 'uv run momentum serve --reload --port 8000')
        Write-Host 'API starting in a new window on http://localhost:8000; web on http://localhost:5173' -ForegroundColor Green
        Run $Web 'pnpm' @('dev')
    }
    'check' {
        Run $Api 'uv' @('run', 'ruff', 'format', '--check', 'momentum', 'tests')
        Run $Api 'uv' @('run', 'ruff', 'check', 'momentum', 'tests')
        Run $Api 'uv' @('run', 'mypy')
        Run $Api 'uv' @('run', 'lint-imports')
        Run $Api 'uv' @('run', 'pytest', '-q')
        Run $Web 'pnpm' @('exec', 'prettier', '--check', '.')
        Run $Web 'pnpm' @('exec', 'eslint', '.')
        Run $Web 'pnpm' @('exec', 'tsc', '-b', '--noEmit')
        Run $Web 'pnpm' @('exec', 'vitest', 'run')
    }
}
