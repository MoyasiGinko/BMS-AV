# ADR 0002: Local development environment on Windows
Status: accepted | Date: 2026-10-07
Context: The build machine is Windows with Python 3.14 default, no `make`, WSL `bash` first on PATH, and a native PostgreSQL 16 service already bound to 5432.
Decision: Use a uv-managed Python 3.12 virtualenv in `.venv`; install GNU make (ezwinports); run `scripts/verify.sh` with Git Bash and `.venv/Scripts` first on PATH;
docker-compose host ports are parameterised (`DB_PORT`, `REDIS_PORT`, default 5432/6379) and the local `.env` uses `DB_PORT=5433`.
Consequences: CI and other machines keep the defaults; the gate itself is unchanged.
