# One command to a working local site:  make dev
PY := .venv/bin/python
-include .env
export

.PHONY: dev db migrate seed run test e2e lint fmt check

dev: db migrate seed run

db:
	docker compose up -d --wait db

migrate:
	$(PY) manage.py migrate

seed:
	$(PY) manage.py seed_demo

run:
	$(PY) manage.py runserver

test:
	$(PY) -m pytest tests/unit

e2e:
	$(PY) -m pytest tests/e2e

lint:
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .

fmt:
	.venv/bin/ruff check --fix .
	.venv/bin/ruff format .

check:
	$(PY) manage.py makemigrations --check --dry-run
	DJANGO_SETTINGS_MODULE=config.settings.production ALLOWED_HOSTS=gymtrainer.onrender.com SECRET_KEY=check-only-$$(date +%s)-not-a-real-key-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx \
		$(PY) manage.py check --deploy --fail-level WARNING
