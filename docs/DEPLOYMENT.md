# Deployment guide

## Recommended hosting model

- Run the FastAPI API and frontend behind a public-facing app node.
- Run Celery workers on trusted compute hosts with Docker access and direct PostgreSQL, RabbitMQ, and Redis connectivity.
- Run exactly one Celery Beat service for the deployment. Beat schedules the submission recovery sweeper; workers alone do not schedule it.
- Keep secrets out of the repository and inject them through deployment secrets or a private `.env` file. Workers do not need API JWT or admin credentials.

The optional Compose worker profile mounts `/var/run/docker.sock`, which grants root-equivalent control over the Docker host. Isolate that host and restrict access to the profile.

## First deployment

1. Create a private environment file and replace the example credentials:

   ```bash
   cp .env.example .env
   ```

2. Build sandbox images and start the services:

   ```bash
   make images
   make up
   ```

3. Apply all migrations and seed initial data if needed:

   ```bash
   make migrate
   make seed
   ```

4. Start workers and a single Beat service:

   ```bash
   docker compose --profile worker up -d --build worker beat
   ```

Scale workers as required, but do not scale Beat. On a host-based development setup, `make worker` embeds Beat for convenience; use a separate Beat process in production.

## Upgrade existing deployments

The batch migration is additive and advances Alembic to `20261101_0002`. Back up PostgreSQL first. Pause API publishing and workers during the broker queue change:

```bash
docker compose stop api
docker compose --profile worker stop worker beat
docker compose exec rabbitmq rabbitmqctl delete_queue codejudge
docker compose build api frontend
docker compose run --rm --no-deps api alembic upgrade head
docker compose up -d api frontend
docker compose --profile worker up -d --build worker beat
```

Deleting the old `codejudge` queue is a one-time upgrade step for deployments whose queue was declared before maximum-priority support. Stop all producers and consumers first: queued broker messages are discarded by the deletion. Their database rows remain; after startup, the sweeper republishes stale pending rows once `BATCH_STALE_PENDING_SECONDS` has elapsed. Do not delete the queue on ordinary restarts or on a fresh install without an existing queue.

The upgraded application declares `codejudge` with `x-max-priority=10`; interactive submissions use priority 5 and batch submissions priority 1. Without recreating an old queue, RabbitMQ can reject the updated declaration because queue arguments are immutable.

## Capacity and environment

All settings are environment-backed. The API loads the private `.env`; Compose passes only worker-specific settings to worker containers so API-only secrets are not exposed.

| Variable | Default | Purpose |
|---|---:|---|
| `BATCH_MAX_ITEMS` | `500` | Maximum expanded submissions in one batch |
| `BATCH_RATE_PER_HOUR` | `20` | Batch creation limit per user per hour |
| `MAX_ACTIVE_SUBMISSIONS_PER_USER` | `1000` | Cap on a user's pending/running submissions |
| `BATCH_REQUEST_MAX_BYTES` | `20971520` | Maximum batch request body (20 MiB) |
| `BATCH_STALE_PENDING_SECONDS` | `120` | Age before the sweeper republishes pending work |
| `WORKER_CONCURRENCY` | CPU count, capped at `4` | Celery concurrency per worker instance |
| `MAX_PARALLEL_CONTAINERS` | 2 x CPU count | Concurrent sandbox cap shared by workers on one host |
| `WORKER_HOST_ID` | Hostname | Redis capacity-lease scope; use the same value for all worker instances on one physical host and a distinct value on each host |
| `WORKER_POOL` | `threads` in Compose/Make | Celery pool; threads are recommended on Windows |
| `DB_POOL_SIZE` | `10` | SQLAlchemy pool size per process |
| `DB_MAX_OVERFLOW` | `20` | Additional SQLAlchemy connections per process |
| `VITE_BATCH_MAX_ITEMS` | `500` | Frontend build-time display limit; keep it aligned with `BATCH_MAX_ITEMS` |

Compose uses the `.env` values for batch limits, worker concurrency, and database pool sizing. For replicas on the same host, keep one shared `WORKER_HOST_ID`; assign different IDs to separate physical hosts. Capacity is enforced per host, not globally across a fleet. Size PostgreSQL connections for the sum of pool sizes and overflow across API and worker processes.

Set `SANDBOX_RUNTIME` only when the configured Docker runtime is installed and available on every worker host. Timing measurements include container overhead and are affected by concurrency; repeat workloads and report medians and the concurrency settings.

## Operating checks

- Confirm all workers consume the `codejudge` queue and Beat is running exactly once.
- Confirm each worker host can access Docker and has both `codejudge-py:1` and `codejudge-cpp:1`.
- Monitor queue depth, pending/running submissions, Redis lease availability, database connection usage, and Docker capacity.
- Use `make test` for the default unit/API suite, `make test-docker` for real sandbox and worker-recovery tests, and `make lint` before deployment.

## Example cloud setup

- DigitalOcean droplets for API and worker compute.
- Neon or Supabase for PostgreSQL.
- CloudAMQP or another managed RabbitMQ service.
- A managed Redis service reachable by API, workers, and Beat.
- GitHub Actions for CI/CD.
