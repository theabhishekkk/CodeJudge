PYTHON ?= python
PIP ?= pip

.PHONY: up down migrate seed images worker test test-docker lint bench frontend

up:
	@docker compose up -d

down:
	@docker compose down -v

migrate:
	@cd backend && python -m alembic upgrade head

seed:
	@cd backend && $(PYTHON) scripts/seed.py

images:
	@bash scripts/build_images.sh

worker:
	@cd backend && celery -A codejudge.worker.celery_app worker --loglevel=info

test:
	@cd backend && pytest

test-docker:
	@cd backend && pytest -m docker

lint:
	@cd backend && ruff check .

bench:
	@cd backend && $(PYTHON) scripts/benchmark.py

frontend:
	@cd frontend && npm install && npm run build
