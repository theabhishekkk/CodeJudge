PYTHON ?= python
CELERY_POOL ?=
WORKER_POOL ?= threads
WORKER_CONCURRENCY ?=
WORKER_POOL_FLAG = $(if $(CELERY_POOL),$(CELERY_POOL),--pool=$(WORKER_POOL))
WORKER_CONCURRENCY_FLAG = $(if $(WORKER_CONCURRENCY),--concurrency=$(WORKER_CONCURRENCY),)

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
	@cd backend && celery -A codejudge.worker.celery_app worker --loglevel=info --queues=codejudge -B $(WORKER_POOL_FLAG) $(WORKER_CONCURRENCY_FLAG)

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
