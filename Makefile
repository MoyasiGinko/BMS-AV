.PHONY: setup verify run seed worker beat test fmt schema css vendor deps-check
RUN := $(shell command -v uv >/dev/null 2>&1 && echo "uv run" || echo "")
setup:
	@command -v uv >/dev/null 2>&1 && uv sync --all-extras || (python -m pip install -U pip && pip install -e ".[dev,ai]")
	-docker compose up -d db redis
	bash scripts/vendor_frontend.sh
	$(RUN) python manage.py migrate
verify:
	bash scripts/verify.sh
run:
	$(RUN) python manage.py tailwind runserver
worker:
	$(RUN) celery -A config worker -l info -Q critical,default,reports,bulk
beat:
	$(RUN) celery -A config beat -l info
seed:
	$(RUN) python manage.py seed_demo
test:
	$(RUN) pytest -q
fmt:
	$(RUN) ruff check --fix . && $(RUN) ruff format .
schema:
	$(RUN) python manage.py spectacular --file docs/openapi.yml --validate --fail-on-warn
css:
	$(RUN) python manage.py tailwind build
vendor:
	bash scripts/vendor_frontend.sh
deps-check:
	-uv lock --check
	$(RUN) pip check
	$(RUN) pip-audit
	$(RUN) python -W error::DeprecationWarning manage.py check
