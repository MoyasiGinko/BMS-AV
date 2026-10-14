# ==============================================================================
# Production Dockerfile for Business OS
# Multi-stage build: Python 3.14 + uv + Gunicorn + Django 6.1
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Build virtual environment, pre-compile assets and collect static
# ------------------------------------------------------------------------------
FROM python:3.14-slim-bookworm AS builder

# Install uv binary from official distribution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install system build dependencies for native wheels (cryptography, psycopg)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies using frozen lockfile
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application source code
COPY . .

# Install project package into virtualenv
RUN uv sync --frozen --no-dev

# Pre-compile Tailwind standalone CSS and collect static assets
ENV DJANGO_SETTINGS_MODULE="config.settings.prod_check" \
    SECRET_KEY="docker-build-placeholder-secret-key-at-least-50-characters-long" \
    ALLOWED_HOSTS="localhost,127.0.0.1"

RUN uv run python manage.py tailwind build || true && \
    uv run python manage.py collectstatic --noinput

# ------------------------------------------------------------------------------
# Stage 2: Minimal runtime image running as unprivileged user
# ------------------------------------------------------------------------------
FROM python:3.14-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# Install minimal runtime dependencies (curl for healthcheck, libpq for PostgreSQL)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    postgresql-client \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create dedicated non-root application user
RUN groupadd -g 10001 appuser && \
    useradd -u 10001 -g appuser -m -d /home/appuser -s /bin/bash appuser

WORKDIR /app

# Copy virtualenv and application assets from builder stage
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appuser /app /app

# Ensure media directory and entrypoint permissions
RUN mkdir -p /app/media && \
    chown -R appuser:appuser /app/media && \
    chmod +x /app/scripts/*.sh

USER appuser

EXPOSE 8000

# Periodic healthcheck probing /healthz
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

ENTRYPOINT ["/app/scripts/entrypoint.sh"]

CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "4", \
     "--worker-class", "gthread", \
     "--threads", "4", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
