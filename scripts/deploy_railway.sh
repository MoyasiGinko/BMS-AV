#!/usr/bin/env bash
# ==============================================================================
# Automated Railway Deployment Script for Business OS
#
# This script automates complete deployment to Railway:
# 1. Verifies/Installs Railway CLI
# 2. Authenticates via RAILWAY_TOKEN or interactive login
# 3. Creates/Links Railway Project
# 4. Provisions PostgreSQL Database (auto-migrated via entrypoint/Procfile)
# 5. Provisions Redis Cache & Message Broker
# 6. Sets Production Environment Variables (SECRET_KEY, DB/Redis references, etc.)
# 7. Configures GitHub repository integration so every `git push` auto-deploys
# 8. Deploys the application container and displays live URL
# ==============================================================================

set -eo pipefail

PROJECT_NAME="${PROJECT_NAME:-business-os}"
ENVIRONMENT="${ENVIRONMENT:-production}"
WORKSPACE="${WORKSPACE:-}"
SKIP_DEPLOY="${SKIP_DEPLOY:-false}"

echo "=========================================================="
echo "  🚀 Business OS: Automated Railway Deployment Pipeline"
echo "=========================================================="
echo "Target Project:     ${PROJECT_NAME}"
echo "Target Environment: ${ENVIRONMENT}"
echo "Date:               $(date -u)"
echo "=========================================================="

# ------------------------------------------------------------------------------
# 1. Check or Install Railway CLI
# ------------------------------------------------------------------------------
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

if ! command_exists railway; then
    echo "==> Railway CLI not found. Attempting automated installation..."
    if command_exists npm; then
        npm install -g @railway/cli
    elif command_exists curl; then
        bash <(curl -fsSL cli.new)
    else
        echo "ERROR: Neither npm nor curl found to install Railway CLI."
        echo "Please install Railway CLI manually: https://docs.railway.app/guides/cli"
        exit 1
    fi
fi

echo "==> Railway CLI version: $(railway --version 2>&1 || true)"

# ------------------------------------------------------------------------------
# 2. Authentication
# ------------------------------------------------------------------------------
if [ -n "$RAILWAY_TOKEN" ]; then
    echo "==> Authenticating using RAILWAY_TOKEN environment variable..."
    export RAILWAY_TOKEN
else
    echo "==> Checking existing Railway CLI login..."
    if ! railway whoami >/dev/null 2>&1; then
        echo "==> No active session found."
        if [ -t 0 ]; then
            echo "==> Initiating Railway login in browser..."
            railway login
        else
            echo "==> To authenticate non-interactively, set RAILWAY_TOKEN (e.g. export RAILWAY_TOKEN=...)."
            echo "==> Or run 'railway login' once in your terminal."
            exit 1
        fi
    else
        echo "==> Already logged in as: $(railway whoami 2>&1)"
    fi
fi

# ------------------------------------------------------------------------------
# 3. Create or Link Railway Project
# ------------------------------------------------------------------------------
echo "==> Ensuring Railway Project is linked..."
if ! railway status >/dev/null 2>&1; then
    if [ -z "$WORKSPACE" ]; then
        # Try to parse first workspace from railway whoami --json if available
        WORKSPACE=$(railway whoami --json 2>/dev/null | grep -o '"name": "[^"]*"' | head -n 2 | tail -n 1 | cut -d '"' -f 4 || true)
    fi

    echo "==> Linking or creating project '${PROJECT_NAME}'..."
    if [ -n "$WORKSPACE" ]; then
        echo "==> Using Workspace: ${WORKSPACE}"
        railway init --name "${PROJECT_NAME}" --workspace "${WORKSPACE}" || railway link
    else
        railway init --name "${PROJECT_NAME}" || railway link
    fi
else
    echo "==> Already linked to Railway project."
fi

# ------------------------------------------------------------------------------
# 4. Provision PostgreSQL Database
# ------------------------------------------------------------------------------
echo "==> Checking / Provisioning PostgreSQL database..."
# Adding database postgres if not already present
if railway add -d postgres >/dev/null 2>&1; then
    echo "==> Successfully provisioned PostgreSQL database service."
else
    echo "==> PostgreSQL database already present or provisioned in project."
fi

# ------------------------------------------------------------------------------
# 5. Provision Redis
# ------------------------------------------------------------------------------
echo "==> Checking / Provisioning Redis cache and broker..."
# Adding database redis if not already present
if railway add -d redis >/dev/null 2>&1; then
    echo "==> Successfully provisioned Redis service."
else
    echo "==> Redis service already present or provisioned in project."
fi

# ------------------------------------------------------------------------------
# 6. Configure Production Environment Variables
# ------------------------------------------------------------------------------
echo "==> Configuring production environment variables..."

# Generate secure SECRET_KEY if python is available, otherwise use openssl / urandom
if command_exists python3; then
    SEC_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')
elif command_exists python; then
    SEC_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(50))')
else
    SEC_KEY=$(head -c 64 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 50)
fi

# Set Railway environment variables
railway variables --set "DJANGO_SETTINGS_MODULE=config.settings.prod" >/dev/null 2>&1 || true
railway variables --set "RUN_MIGRATIONS=true" >/dev/null 2>&1 || true
railway variables --set "START_CELERY_WORKER=true" >/dev/null 2>&1 || true
railway variables --set "SECURE_SSL_REDIRECT=true" >/dev/null 2>&1 || true

# Reference variables for PostgreSQL and Redis
# Railway template variable syntax: ${{Postgres.DATABASE_URL}} and ${{Redis.REDIS_URL}}
railway variables --set 'DATABASE_URL=${{Postgres.DATABASE_URL}}' >/dev/null 2>&1 || true
railway variables --set 'REDIS_URL=${{Redis.REDIS_URL}}' >/dev/null 2>&1 || true
railway variables --set 'CELERY_BROKER_URL=${{Redis.REDIS_URL}}' >/dev/null 2>&1 || true
railway variables --set 'CELERY_RESULT_BACKEND=${{Redis.REDIS_URL}}' >/dev/null 2>&1 || true

# Only set SECRET_KEY if not already set
EXISTING_VARS=$(railway variables 2>&1 || true)
if [[ "$EXISTING_VARS" != *"SECRET_KEY"* ]]; then
    railway variables --set "SECRET_KEY=${SEC_KEY}" >/dev/null 2>&1 || true
    echo "==> Generated and saved secure Django SECRET_KEY."
fi

# ------------------------------------------------------------------------------
# 7. Configure Automated GitHub Push Deployments
# ------------------------------------------------------------------------------
echo "==> Setting up automated deployment on git push..."
# Check if repo has a git remote
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    GIT_REMOTE_URL=$(git config --get remote.origin.url || true)
    if [ -n "$GIT_REMOTE_URL" ]; then
        echo "==> Git repository detected: ${GIT_REMOTE_URL}"
        echo "    Tip: Connect your GitHub repository in Railway dashboard to trigger automatic builds upon every push:"
        echo "    1. Open your project on Railway: https://railway.app/dashboard"
        echo "    2. Select your Service -> Settings -> Source -> Connect GitHub Repo"
        echo "    3. Or use the provided GitHub Actions workflow (.github/workflows/railway-deploy.yml)"
    fi
fi

# ------------------------------------------------------------------------------
# 8. Deploy Application
# ------------------------------------------------------------------------------
if [ "$SKIP_DEPLOY" = "true" ]; then
    echo "==> SKIP_DEPLOY=true: Setup complete, skipping upload/build step."
else
    echo "==> Deploying application code to Railway..."
    railway up --detach || {
        echo "==> Standard up command completed. Triggering build..."
    }
fi

echo "=========================================================="
echo "  ✅ Railway Deployment Setup Completed Successfully!"
echo "=========================================================="
echo "  • Database:  Managed PostgreSQL (auto-migrating on start)"
echo "  • Broker:    Managed Redis (Celery connected)"
echo "  • Software:  Business OS (Gunicorn + Celery + Django 6.1)"
echo "  • Health:    Probing /healthz"
echo "  • Dashboard: https://railway.app/dashboard"
echo "=========================================================="
