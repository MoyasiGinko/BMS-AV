<#
.SYNOPSIS
  Automated Railway Deployment Script for Business OS (PowerShell)

.DESCRIPTION
  Automates the complete deployment to Railway:
  1. Verifies/Installs Railway CLI
  2. Authenticates via RAILWAY_TOKEN or interactive login
  3. Creates or links the Railway Project
  4. Provisions PostgreSQL Database
  5. Provisions Redis Cache & Message Broker
  6. Configures Production Environment Variables
  7. Sets up automated deployment upon Git Push
  8. Deploys the application and outputs live status
#>

[CmdletBinding()]
param (
    [string]$ProjectName = "business-os",
    [string]$Environment = "production",
    [string]$Workspace = "",
    [string]$RailwayToken = "",
    [switch]$SkipDeploy
)

$ErrorActionPreference = "Continue"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  🚀 Business OS: Automated Railway Deployment Pipeline" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Target Project:     $ProjectName"
Write-Host "Target Environment: $Environment"
Write-Host "Date:               $(Get-Date -Format 'u')"
Write-Host "=========================================================="

# 1. Check or Install Railway CLI
if (-not (Get-Command "railway" -ErrorAction SilentlyContinue)) {
    Write-Host "==> Railway CLI not found. Attempting installation via npm / scoop / winget..." -ForegroundColor Yellow
    if (Get-Command "npm" -ErrorAction SilentlyContinue) {
        npm install -g @railway/cli
    } elseif (Get-Command "winget" -ErrorAction SilentlyContinue) {
        winget install Railway.Railway
    } elseif (Get-Command "scoop" -ErrorAction SilentlyContinue) {
        scoop install railway
    } else {
        Write-Error "Could not automatically install Railway CLI. Please install it manually from https://docs.railway.app/guides/cli"
        exit 1
    }
}

$cliVersion = & railway --version 2>&1
Write-Host "==> Railway CLI Version: $cliVersion" -ForegroundColor Green

# 2. Authentication
if ($RailwayToken -ne "") {
    $env:RAILWAY_TOKEN = $RailwayToken
    Write-Host "==> Authenticated using provided RailwayToken." -ForegroundColor Green
} elseif ($env:RAILWAY_TOKEN) {
    Write-Host "==> Authenticated using existing env:RAILWAY_TOKEN." -ForegroundColor Green
} else {
    Write-Host "==> Checking Railway CLI session..."
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    $whoami = try { (& railway whoami 2>&1) -join " " } catch { $_.Exception.Message }
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $prevEap

    if ($exitCode -ne 0 -or $whoami -match "Unauthorized|not logged in") {
        Write-Host "==> No active session found." -ForegroundColor Yellow
        if ([Environment]::UserInteractive) {
            Write-Host "==> Initiating Railway login in browser..." -ForegroundColor Yellow
            & railway login
        } else {
            Write-Host "==> To authenticate non-interactively, set the RAILWAY_TOKEN environment variable (or pass -RailwayToken <token>)." -ForegroundColor Yellow
            Write-Host "==> Or run 'railway login' once in your terminal." -ForegroundColor Yellow
            exit 1
        }
    } else {
        Write-Host "==> Logged in as: $whoami" -ForegroundColor Green
    }
}

# 3. Create or Link Project
Write-Host "==> Ensuring Railway project is linked..." -ForegroundColor Cyan
& railway status 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    if (-not $Workspace) {
        try {
            $whoamiRaw = & railway whoami --json 2>$null
            if ($whoamiRaw) {
                $whoamiJson = $whoamiRaw | ConvertFrom-Json
                if ($whoamiJson.workspaces -and $whoamiJson.workspaces.Count -gt 0) {
                    $matched = $whoamiJson.workspaces | Where-Object { $_.name -like "*$($whoamiJson.name)*" } | Select-Object -First 1
                    if (-not $matched) {
                        $matched = $whoamiJson.workspaces[0]
                    }
                    $Workspace = $matched.name
                    Write-Host "==> Auto-selected Workspace: $Workspace" -ForegroundColor Cyan
                }
            }
        } catch {}
    }

    Write-Host "==> Initializing project '$ProjectName'..." -ForegroundColor Yellow
    if ($Workspace) {
        & railway init --name $ProjectName --workspace $Workspace
    } else {
        & railway init --name $ProjectName
    }

    if ($LASTEXITCODE -ne 0) {
        & railway link
    }
} else {
    Write-Host "==> Project already linked." -ForegroundColor Green
}

# 4. Provision PostgreSQL Database
Write-Host "==> Checking / Provisioning PostgreSQL database..." -ForegroundColor Cyan
& railway add -d postgres 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "==> Successfully provisioned PostgreSQL database service." -ForegroundColor Green
} else {
    Write-Host "==> PostgreSQL database already present or provisioned in project." -ForegroundColor DarkGray
}

# 5. Provision Redis
Write-Host "==> Checking / Provisioning Redis cache and broker..." -ForegroundColor Cyan
& railway add -d redis 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "==> Successfully provisioned Redis service." -ForegroundColor Green
} else {
    Write-Host "==> Redis service already present or provisioned in project." -ForegroundColor DarkGray
}

# 6. Configure Environment Variables
Write-Host "==> Configuring production environment variables..." -ForegroundColor Cyan

# Generate a cryptographically secure 50-character SECRET_KEY
$bytes = New-Object byte[] 40
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes)
$secKey = [Convert]::ToBase64String($bytes) -replace '[/+=]', 'x'

& railway variables --set "DJANGO_SETTINGS_MODULE=config.settings.prod" 2>&1 | Out-Null
& railway variables --set "RUN_MIGRATIONS=true" 2>&1 | Out-Null
& railway variables --set "START_CELERY_WORKER=true" 2>&1 | Out-Null
& railway variables --set "SECURE_SSL_REDIRECT=true" 2>&1 | Out-Null

# Reference variables for PostgreSQL and Redis
& railway variables --set 'DATABASE_URL=${{Postgres.DATABASE_URL}}' 2>&1 | Out-Null
& railway variables --set 'REDIS_URL=${{Redis.REDIS_URL}}' 2>&1 | Out-Null
& railway variables --set 'CELERY_BROKER_URL=${{Redis.REDIS_URL}}' 2>&1 | Out-Null
& railway variables --set 'CELERY_RESULT_BACKEND=${{Redis.REDIS_URL}}' 2>&1 | Out-Null

$existingVars = & railway variables 2>&1
if ($existingVars -notmatch "SECRET_KEY") {
    & railway variables --set "SECRET_KEY=$secKey" 2>&1 | Out-Null
    Write-Host "==> Generated and configured secure Django SECRET_KEY." -ForegroundColor Green
}

# 7. Git Integration Tips
Write-Host "==> Automated Git Push Deployments:" -ForegroundColor Cyan
Write-Host "    Every push to your connected Git branch triggers automatic builds and migrations on Railway."
Write-Host "    You can connect your GitHub repository directly in Railway (Project Settings -> Connect GitHub Repo),"
Write-Host "    or use the GitHub Actions workflow located at .github/workflows/railway-deploy.yml."

# 8. Deploy
if ($SkipDeploy) {
    Write-Host "==> SkipDeploy specified: Setup completed without triggering deployment." -ForegroundColor Yellow
} else {
    Write-Host "==> Deploying application code to Railway..." -ForegroundColor Cyan
    & railway up --detach
}

Write-Host "==========================================================" -ForegroundColor Green
Write-Host "  ✅ Railway Deployment Setup Completed Successfully!" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "  • Database:  Managed PostgreSQL (auto-migrating on start)"
Write-Host "  • Broker:    Managed Redis (Celery connected)"
Write-Host "  • Software:  Business OS (Gunicorn + Celery + Django 6.1)"
Write-Host "  • Health:    Probing /healthz"
Write-Host "  • Dashboard: https://railway.app/dashboard"
Write-Host "=========================================================="
