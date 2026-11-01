PYTHON ?= python
CELERY_POOL ?=

.PHONY: up down migrate seed images worker test test-docker lint bench frontend

up:
	@docker compose up -d --build --wait postgres rabbitmq redis api frontend

down:
	@docker compose down

migrate:
	@docker compose exec -T api alembic upgrade head

seed:
	@docker compose exec -T api python scripts/seed.py

images:
	@bash scripts/build_images.sh

worker:
	@cd backend && celery -A codejudge.worker.celery_app worker --loglevel=info --queues=codejudge $(CELERY_POOL)

test:
	@cd backend && $(PYTHON) -m pytest

test-docker:
	@cd backend && $(PYTHON) -m pytest -m docker

lint:
	@cd backend && $(PYTHON) -m ruff check .

bench:
	@$(PYTHON) scripts/benchmark.py

frontend:
	@cd frontend && npm ci && npm run build
