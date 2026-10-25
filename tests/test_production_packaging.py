"""Tests for production packaging, containerization, and operational disaster recovery tooling."""

from __future__ import annotations

import gzip
import importlib
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.management import call_command

import config.settings.prod as prod_settings

BASE_DIR = Path(__file__).resolve().parent.parent


def test_dockerfile_structure_and_security_configuration() -> None:
    """Verify Dockerfile uses multi-stage build, uv, non-root user, and health check."""
    dockerfile_path = BASE_DIR / "Dockerfile"
    assert dockerfile_path.exists(), "Dockerfile must exist at repository root"
    content = dockerfile_path.read_text(encoding="utf-8")

    # Multi-stage architecture
    assert "AS builder" in content
    assert "AS runtime" in content
    assert "uv sync" in content

    # Non-root user security
    assert "useradd -u 10001" in content
    assert "USER appuser" in content

    # Healthcheck and WSGI
    assert "HEALTHCHECK" in content
    assert "/healthz" in content
    assert "EXPOSE 8000" in content
    assert "gunicorn" in content
    assert "config.wsgi:application" in content
    assert "entrypoint.sh" in content


def test_docker_compose_prod_services_and_topology() -> None:
    """Verify docker-compose.prod.yml defines all 6 required production services and volumes."""
    compose_path = BASE_DIR / "docker-compose.prod.yml"
    assert compose_path.exists(), "docker-compose.prod.yml must exist at repository root"
    content = compose_path.read_text(encoding="utf-8")

    # All 6 required services
    assert "db:" in content
    assert "redis:" in content
    assert "web:" in content
    assert "worker:" in content
    assert "beat:" in content
    assert "caddy:" in content

    # PostgreSQL 18 & Redis 8
    assert "postgres:18" in content
    assert "redis:8" in content

    # Network isolation and healthchecks
    assert "networks:" in content
    assert "internal" in content
    assert "public" in content
    assert "healthcheck:" in content

    # Persistent storage volumes
    assert "db_data:" in content
    assert "redis_data:" in content
    assert "media_volume:" in content


def test_reverse_proxy_configurations_present() -> None:
    """Verify Caddyfile and Nginx configuration files exist and declare essential directives."""
    caddy_path = BASE_DIR / "Caddyfile"
    assert caddy_path.exists()
    caddy_content = caddy_path.read_text(encoding="utf-8")
    assert "reverse_proxy web:8000" in caddy_content
    assert "encode zstd gzip" in caddy_content
    assert "handle /static/*" in caddy_content

    nginx_path = BASE_DIR / "nginx" / "nginx.conf"
    assert nginx_path.exists()
    nginx_content = nginx_path.read_text(encoding="utf-8")
    assert "upstream django" in nginx_content
    assert "proxy_pass http://django" in nginx_content
    assert "gzip on;" in nginx_content


def test_environment_documentation_and_example_template() -> None:
    """Verify .env.example and docs/05-production-packaging.md document all required production variables."""
    env_example = BASE_DIR / ".env.example"
    assert env_example.exists()
    env_content = env_example.read_text(encoding="utf-8")

    critical_vars = [
        "SECRET_KEY",
        "DATABASE_URL",
        "REDIS_URL",
        "CELERY_BROKER_URL",
        "FIELD_ENCRYPTION_KEY",
        "ALLOWED_HOSTS",
        "SECURE_SSL_REDIRECT",
        "SECURE_HSTS_SECONDS",
    ]
    for var_name in critical_vars:
        assert f"{var_name}=" in env_content, f"Missing {var_name} in .env.example"

    doc_path = BASE_DIR / "docs" / "05-production-packaging.md"
    assert doc_path.exists()
    doc_content = doc_path.read_text(encoding="utf-8")
    assert "Architecture Topology" in doc_content
    assert "Environment Variables Reference" in doc_content
    assert "Quickstart Deployment Guide" in doc_content


def test_entrypoint_script_structure() -> None:
    """Verify scripts/entrypoint.sh contains wait_for_db and migration handling."""
    entrypoint = BASE_DIR / "scripts" / "entrypoint.sh"
    assert entrypoint.exists()
    content = entrypoint.read_text(encoding="utf-8")
    assert "wait_for_db" in content
    assert "migrate" in content
    assert 'exec "$@"' in content


@pytest.mark.django_db
def test_wait_for_db_command_execution() -> None:
    """Verify wait_for_db management command executes cleanly when database is connected."""
    call_command("wait_for_db", timeout=5, interval=0.1)


def test_backup_and_restore_python_utilities(tmp_path: Path) -> None:
    """Verify scripts/backup.py and scripts/restore.py work with compression and SHA256 verification."""
    backup_py = BASE_DIR / "scripts" / "backup.py"
    restore_py = BASE_DIR / "scripts" / "restore.py"
    assert backup_py.exists()
    assert restore_py.exists()

    # 1. Run backup in --dry-run mode
    cmd_backup = [sys.executable, str(backup_py), "--output-dir", str(tmp_path), "--dry-run"]
    res_backup = subprocess.run(cmd_backup, capture_output=True, text=True, check=False)
    assert res_backup.returncode == 0, f"backup.py failed: {res_backup.stdout}\n{res_backup.stderr}"

    # Verify backup archive and checksum created
    backup_files = list(tmp_path.glob("bos_backup_*.sql.gz"))
    assert len(backup_files) == 1
    archive_path = backup_files[0]
    checksum_path = tmp_path / f"{archive_path.name}.sha256"
    assert checksum_path.exists()

    # Verify content readable via gzip
    with gzip.open(archive_path, "rt", encoding="utf-8") as f:
        header = f.readline()
    assert "Business OS" in header

    # 2. Run restore in --dry-run mode
    cmd_restore = [sys.executable, str(restore_py), str(archive_path), "--dry-run"]
    res_restore = subprocess.run(cmd_restore, capture_output=True, text=True, check=False)
    assert res_restore.returncode == 0, f"restore.py failed: {res_restore.stdout}\n{res_restore.stderr}"
    assert "SHA256 checksum verification: OK!" in res_restore.stdout
    assert "Header verification successful" in res_restore.stdout


def test_backup_and_restore_shell_scripts_exist() -> None:
    """Verify POSIX shell scripts scripts/backup.sh and scripts/restore.sh exist with valid logic."""
    backup_sh = BASE_DIR / "scripts" / "backup.sh"
    restore_sh = BASE_DIR / "scripts" / "restore.sh"
    assert backup_sh.exists()
    assert restore_sh.exists()

    content_backup = backup_sh.read_text(encoding="utf-8")
    assert "pg_dump" in content_backup
    assert "gzip -9" in content_backup

    content_restore = restore_sh.read_text(encoding="utf-8")
    assert "gunzip -c" in content_restore
    assert "psql" in content_restore
    assert "sha256sum" in content_restore or "shasum" in content_restore


def test_railway_deployment_configuration_and_scripts() -> None:
    """Verify railway.json, railway.toml, Procfile, deploy scripts, and GitHub action workflow."""
    railway_json = BASE_DIR / "railway.json"
    assert railway_json.exists(), "railway.json must exist at repository root"
    json_content = railway_json.read_text(encoding="utf-8")
    assert "DOCKERFILE" in json_content
    assert "/healthz" in json_content

    railway_toml = BASE_DIR / "railway.toml"
    assert railway_toml.exists(), "railway.toml must exist at repository root"
    toml_content = railway_toml.read_text(encoding="utf-8")
    assert "DOCKERFILE" in toml_content
    assert "/healthz" in toml_content

    procfile = BASE_DIR / "Procfile"
    assert procfile.exists(), "Procfile must exist at repository root"
    proc_content = procfile.read_text(encoding="utf-8")
    assert "release: python manage.py migrate --noinput" in proc_content
    assert "web: gunicorn" in proc_content
    assert "worker: celery" in proc_content

    deploy_sh = BASE_DIR / "scripts" / "deploy_railway.sh"
    assert deploy_sh.exists(), "scripts/deploy_railway.sh must exist"
    sh_content = deploy_sh.read_text(encoding="utf-8")
    assert "railway add -d postgres" in sh_content
    assert "railway add -d redis" in sh_content
    assert "railway up" in sh_content

    deploy_ps1 = BASE_DIR / "scripts" / "deploy_railway.ps1"
    assert deploy_ps1.exists(), "scripts/deploy_railway.ps1 must exist"
    ps1_content = deploy_ps1.read_text(encoding="utf-8")
    assert "railway add -d postgres" in ps1_content
    assert "railway add -d redis" in ps1_content
    assert "railway up" in ps1_content

    workflow = BASE_DIR / ".github" / "workflows" / "railway-deploy.yml"
    assert workflow.exists(), "GitHub workflow railway-deploy.yml must exist"
    wf_content = workflow.read_text(encoding="utf-8")
    assert "on:" in wf_content
    assert "push:" in wf_content
    assert "deploy_railway.sh" in wf_content


def test_railway_prod_settings_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify config.settings.prod automatically integrates Railway public domain into ALLOWED_HOSTS."""
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-railway-prod-testing-at-least-50-characters")
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "bms-test.up.railway.app")

    importlib.reload(prod_settings)

    assert "bms-test.up.railway.app" in prod_settings.ALLOWED_HOSTS
    assert ".railway.app" in prod_settings.ALLOWED_HOSTS
    assert "https://bms-test.up.railway.app" in prod_settings.CSRF_TRUSTED_ORIGINS
