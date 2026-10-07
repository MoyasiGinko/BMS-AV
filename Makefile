.PHONY: setup verify run seed worker test fmt schema
setup:
	python -m pip install -U pip && pip install -e ".[dev]"
	-docker compose up -d db redis
	python manage.py migrate
verify:
	bash scripts/verify.sh
run:
	python manage.py runserver 0.0.0.0:8000
worker:
	celery -A config worker -l info -Q critical,default,reports,bulk
seed:
	python manage.py seed_demo
test:
	pytest -q
fmt:
	ruff check --fix . && ruff format .
schema:
	python manage.py spectacular --file docs/openapi.yml --validate --fail-on-warn
