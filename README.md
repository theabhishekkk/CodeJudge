# CodeJudge

> **Grade generated code without trusting it.**

CodeJudge is a self-hostable online judge and evaluation harness for AI-generated code. Submit one solution or a full experiment batch; each test runs in a fresh, resource-limited Docker sandbox—not in the API process.

![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/UI-React-61DAFB?logo=react&logoColor=black)
![Docker](https://img.shields.io/badge/Execution-Docker-2496ED?logo=docker&logoColor=white)

**Python 3 · C++17 · AC / WA / RE / TLE / MLE · batch runs · CSV research exports**

### Built for safe grading and useful results

| Run safely | Test at scale | Understand outcomes |
|---|---|---|
| Network-isolated containers with CPU, memory, process, and filesystem limits | Submit files, JSONL, JSON, or CSV; track live batch progress | Inspect verdicts and per-test resource metrics, export results, and compare model runs |

Use the built-in A+B demo to exercise all five verdicts. For the system design and deployment model, see [Architecture](docs/ARCHITECTURE.md) and [Deployment](docs/DEPLOYMENT.md). Planning to host CodeJudge? Start with the deployment guide—it explains why sandbox workers should run separately from the public-facing API.

**Verdicts:** Accepted (`AC`), Wrong Answer (`WA`), Runtime Error (`RE`), Time Limit Exceeded (`TLE`), and Memory Limit Exceeded (`MLE`).

## Architecture

```text
Browser / API client
        │
        ▼
FastAPI ─── PostgreSQL
   │           ▲
   ├── Redis   │
   ▼           │
RabbitMQ → Celery worker → fresh Docker sandbox per test
```

- **FastAPI** handles authentication, problems, single and batch submission requests, history, and statistics.
- **PostgreSQL** stores users, problems, test cases, batches, submissions, and per-test metrics.
- **RabbitMQ and Celery** provide asynchronous grading on the priority-enabled `codejudge` queue.
- **Redis** is used as the Celery result backend, for per-host sandbox capacity leases, worker heartbeats, and recovery coordination.
- **Docker** runs each untrusted solution in a short-lived, resource-limited container with networking disabled.
- **Celery Beat** periodically recovers stale queued work and finalizes batches after worker loss.
- **React, TypeScript, and Vite** provide registration/login, problem solving, batch creation/history/live progress, submission polling/history, and the dashboard.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for more detail.

## Contents

- [Quickstart](#quickstart-docker-desktop-or-docker-engine)
- [Using the application](#using-the-application)
- [Batch input formats](#batch-input-formats)
- [API examples](#api-examples)
- [Batch API reference](#batch-api-reference)
- [Research and load-test scripts](#research-and-load-test-scripts)
- [Configuration](#configuration)
- [Development and verification](#development-and-verification)
- [Security and limitations](#security-and-limitations)
- [Deployment and upgrades](#deployment-and-upgrades)
- [Windows & WSL2 troubleshooting](#windows--wsl2-troubleshooting)

## Quickstart (Docker Desktop or Docker Engine)

### Prerequisites

- Docker Engine or Docker Desktop with the Compose plugin.
- Bash (Linux, macOS, Git Bash, or WSL) for the `make images` target.
- Python 3.11+ for a host-based worker and backend development.
- Node.js 20+ and npm for frontend development. The frontend container builds using Node 20.
- A Docker daemon accessible to the worker. Sandbox images must be built on each worker host.

### Start a local stack

1. Copy the example environment file. Set a private `JWT_SECRET`, admin password, and database/broker passwords before exposing the service outside a trusted local machine:

   ```bash
   cp .env.example .env
   ```

   `.env` is private local configuration and must not be committed. Values in `.env.example` are development defaults, not production credentials.

2. Build the Python and C++ sandbox images. The images run only inside Docker; the API does not execute submitted code:

   ```bash
   make images
   ```

3. Build and start PostgreSQL, RabbitMQ, Redis, the API, and the Nginx-served frontend. The command waits for service health checks:

   ```bash
   make up
   ```

4. Apply database migrations and seed the configured admin account plus six sample problems (including A+B):

   ```bash
   make migrate
   make seed
   ```

5. Start one grading worker. In development, the worker runs on the host so the Docker bind-mount paths are valid. Install the backend package in the Python environment first:

   ```bash
   python -m pip install -e backend
   make worker WORKER_POOL=threads WORKER_CONCURRENCY=4
   ```

   This development command includes Celery Beat (`-B`) to run periodic recovery. `make worker` loads the repository-root `.env` before starting Celery, including when the worker runs from `backend/`. Threads are also recommended for Windows; do not start another Beat service at the same time.

   ```bash
   # Stop with Ctrl+C when finished.
   ```

6. Open the application at <http://localhost:5173>. The API is at <http://localhost:8000>; interactive API documentation is at <http://localhost:8000/docs>. API health is available at <http://localhost:8000/api/health>.

`make migrate` and `make seed` execute inside the running API container; the host does not need Alembic or database client packages for those commands.

### Run workers in Docker instead

Use this instead of the host worker above. It starts one worker and exactly one Beat scheduler:

```bash
docker compose --profile worker up -d --build worker beat
```

The worker mounts `/var/run/docker.sock` and the sandbox work directory; Docker socket access gives the worker control over the host Docker daemon (effectively root-equivalent access). Use this only on a trusted, isolated machine. Scale workers only after reviewing [capacity configuration](#configuration). If running a host worker with `make worker`, do not also start the Compose Beat service. To stop the Compose worker profile, run `docker compose --profile worker down`.

### Vite development frontend

The Compose frontend serves the production build on port 5173. To use Vite hot reload instead, stop that service first, install the locked dependencies, then run:

```bash
docker compose stop frontend
cd frontend
npm ci
npm run dev
```

Vite listens on <http://localhost:5173> and uses `VITE_API_URL`, defaulting to `http://localhost:8000/api`. The API must allow the frontend origin in `CORS_ALLOW_ORIGINS`.

## Using the application

1. Register at `/register` or sign in at `/login`.
2. Choose a challenge from `/problems`, then open a problem such as `/problem/1`.
3. Select Python 3 or C++17, edit the starter code, and submit.
4. The submission page polls every second until grading completes. It displays the verdict, wall/CPU time, peak memory, and per-test metrics without revealing hidden inputs or expected outputs.
5. Review history at `/submissions` and runtime, memory, pass-rate, and verdict statistics at `/dashboard`.
6. Create a batch at `/batch`, then monitor it at `/batches` or `/batch/{id}`. The batch page accepts source files, JSONL, JSON, or CSV; it validates and previews rows before submission. The seeded A+B problem can be used with the 120-sample demo button to exercise correct, wrong, runtime-error, timeout, and memory-limit verdicts.

The frontend stores the JWT access token in local storage and attaches it to authenticated API calls. Unauthorized responses sign the user out; API/network and rate-limit errors appear as notices.

### Batch creation and monitoring

The batch page (`/batch`) provides three input modes:

1. **Source files:** drop or select `.py`, `.cpp`, and `.cc` files. Choose one problem for the selected files; file extensions determine Python 3 or C++17, and filenames are used as sample IDs.
2. **Upload data:** upload a `.jsonl`, `.json`, or `.csv` file. A template CSV can be downloaded from this page.
3. **Paste JSONL:** enter one submission object per line.

The page validates inputs locally, lists row/line errors, shows a preview, and displays the total number of submissions after repeats. Optional batch and model names are available. The **Load demo batch** button creates 120 samples for the seeded A+B problem. On the live page, view progress and ETA, verdict distribution, timing/memory metrics, filter and sort submissions, export CSV, cancel pending work, re-run failed items, or copy a link. Demo batches additionally show expected-versus-actual verdict checks.

`/batches` lists prior batches; `/batch/{id}` opens a batch. Batch links and all batch endpoints require authentication and are restricted to the owning user (admins can access according to API authorization rules).

## Batch input formats

Every input row has these fields:

| Field | Required | Valid values / limit |
|---|---:|---|
| `problem_id` | Yes | Positive integer for an existing problem |
| `language_id` | Yes | `python3` or `cpp17` |
| `source_code` | Yes | Non-empty string, at most 64 KiB UTF-8 |
| `sample_id` | No | String of at most 255 characters |

JSONL contains one object per non-empty line:

```jsonl
{"problem_id":1,"language_id":"python3","source_code":"print(sum(map(int, input().split())))","sample_id":"python-model-a-001"}
{"problem_id":1,"language_id":"cpp17","source_code":"#include <iostream>\nint main(){int a,b; std::cin>>a>>b; std::cout<<a+b<<'\\n';}","sample_id":"cpp-model-b-001"}
```

JSON may be an array of rows or an object with an `items` array:

```json
{
  "items": [
    {
      "problem_id": 1,
      "language_id": "python3",
      "source_code": "print(sum(map(int, input().split())))",
      "sample_id": "sample-001"
    }
  ]
}
```

CSV must include `problem_id`, `language_id`, and `source_code` headers; `sample_id` is optional. Quote source code containing commas, quotes, or newlines using standard CSV quoting:

```csv
problem_id,language_id,source_code,sample_id
1,python3,"print(sum(map(int, input().split())))",sample-001
1,cpp17,"#include <iostream>
int main() { int a, b; std::cin >> a >> b; std::cout << a + b << '\n'; }",sample-002
```

Batch requests support `repeats` from 1 to 10. The server creates a separate submission for each input/repeat pair and assigns zero-based `repeat_index` values. At the default `BATCH_MAX_ITEMS=500`, the number of input rows multiplied by repeats cannot exceed 500. The HTTP request body defaults to 20 MiB; source code has the stricter per-item 64 KiB limit. Validation is performed before the batch is stored; invalid rows return HTTP 422 with item indexes and field-level messages.

The per-user batch creation rate defaults to 20 per hour. The limit on pending and running submissions defaults to 1,000 per user and may reject creation with HTTP 429. Batch jobs use RabbitMQ priority 1, while interactive single submissions use priority 5, so interactive submissions are favored when both are queued.

## API examples

Register and capture the access token:

```bash
TOKEN=$(curl -sS -X POST http://localhost:8000/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"user@example.com","password":"secret123"}' | python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
```

Get the problem list and public samples:

```bash
curl -sS http://localhost:8000/api/problems \
  -H "Authorization: Bearer $TOKEN"

curl -sS http://localhost:8000/api/problems/1 \
  -H "Authorization: Bearer $TOKEN"
```

Submit an A+B solution. The API responds with HTTP `202` and a submission ID; poll that ID for the result:

```bash
SUBMISSION_ID=$(curl -sS -X POST http://localhost:8000/api/submissions \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"problem_id":1,"language_id":"python3","source_code":"print(sum(map(int, input().split())))"}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')

curl -sS "http://localhost:8000/api/submissions/$SUBMISSION_ID" \
  -H "Authorization: Bearer $TOKEN"
```

List submissions and view your statistics:

```bash
curl -sS 'http://localhost:8000/api/submissions?limit=50&offset=0' \
  -H "Authorization: Bearer $TOKEN"

curl -sS http://localhost:8000/api/stats/summary \
  -H "Authorization: Bearer $TOKEN"
```

The UI also accepts `/submissions` as an alias for submission create/read/list routes. Hidden test data is never included in problem details or submission results.

### Batch API

All routes below are under `/api`. Authenticate with a bearer access token, returned by `POST /api/auth/register` or `POST /api/auth/login`. For local development, the first registered user is assigned the admin role; `make seed` creates the configured admin account and demo problems.

Create a batch with JSON items. CSV and JSONL files can also be uploaded in the UI or passed to the benchmark script:

```bash
BATCH_ID=$(curl -sS -X POST http://localhost:8000/api/batches \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"example","model_name":"model-x","repeats":1,"items":[{"problem_id":1,"language_id":"python3","source_code":"print(sum(map(int, input().split())))","sample_id":"sample-1"}]}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')

curl -sS "http://localhost:8000/api/batches/$BATCH_ID" \
  -H "Authorization: Bearer $TOKEN"
curl -sS "http://localhost:8000/api/batches/$BATCH_ID/items?limit=50&offset=0" \
  -H "Authorization: Bearer $TOKEN"
curl -sS "http://localhost:8000/api/batches/$BATCH_ID/export.csv" \
  -H "Authorization: Bearer $TOKEN" -o batch.csv
```

Batch endpoints also support cancellation (`POST /api/batches/{id}/cancel`), re-running failed items (`POST /api/batches/{id}/rerun-failed`), and item filters for status, verdict, problem, language, and sort order. Cancellation stops pending submissions; already-running sandboxes finish normally. `GET /api/stats/summary?batch_id={id}` scopes statistics to an owned batch. All batch endpoints enforce ownership. Hidden test data is never included in problem details or submission results.

### Batch API reference

| Method and path | Description |
|---|---|
| `POST /api/batches` | Create and queue a batch; returns HTTP 202 with batch `id`, expanded `total`, and initial `status` |
| `GET /api/batches?limit=50&offset=0` | List the authenticated user's batches and progress summaries |
| `GET /api/batches/{id}` | Fetch batch status, item counts, verdict distribution, throughput/ETA, and timing/memory summaries |
| `GET /api/batches/{id}/items` | Fetch a page of result rows; defaults to 50 rows, maximum 100 |
| `GET /api/batches/{id}/export.csv` | Download all batch result rows as CSV |
| `POST /api/batches/{id}/cancel` | Cancel pending rows; rows already running are allowed to finish |
| `POST /api/batches/{id}/rerun-failed` | Create a new batch containing errored or non-AC completed items |
| `GET /api/stats/summary?batch_id={id}` | Return regular statistics scoped to an owned batch |

`GET /api/batches/{id}/items` accepts `limit` (1–100), `offset` (0 or higher), `verdict`, `status`, `problem_id`, `language_id`, `sort`, and `include_code`. Supported sort fields are `created_at`, `status`, `verdict`, `problem_id`, `language_id`, `wall_ms`, and `memory_kb`; prefix a field with `-` for descending order (for example `sort=-wall_ms`). `include_code` defaults to false. CSV export includes submission identifiers, model/sample metadata, repeat index, verdict/status, resource measurements, timestamps, and bounded error detail; it does not export source code or hidden test inputs.

Batch status is `RUNNING`, `COMPLETED`, or `CANCELLED`. Submission status is `PENDING`, `RUNNING`, `COMPLETED`, `ERROR`, or `CANCELLED`. A completed submission has a verdict such as `AC`, `WA`, `RE`, `TLE`, or `MLE`. Poll the batch summary and items endpoint rather than relying on Celery task result IDs.

Creation validation checks every problem/language/source row before insertion. It also checks the configured batch size, per-user rate limit, and active-submission limit. Typical errors are HTTP 401 for missing/invalid authentication, 403 for a resource not owned by the caller, 404 for a missing batch/problem, 422 for invalid request data, 429 for rate/active-submission limits, and 503 if Redis-backed rate limiting is unavailable. A 429 response may include `Retry-After`.

### Example: cancel or re-run a batch

```bash
# Cancellation leaves running items alone; only pending items are cancelled.
curl -sS -X POST "http://localhost:8000/api/batches/$BATCH_ID/cancel" \
  -H "Authorization: Bearer $TOKEN"

# Re-run failed items creates a distinct new batch and returns its new ID.
curl -sS -X POST "http://localhost:8000/api/batches/$BATCH_ID/rerun-failed" \
  -H "Authorization: Bearer $TOKEN"
```

## Seed data and research scripts

`make seed` creates the admin account using `ADMIN_EMAIL` and `ADMIN_PASSWORD` if it does not exist, then seeds six problems with public sample and hidden test cases. Set these variables in `.env` before seeding if you need different credentials. Seed is safe to rerun: existing users, problems, and test cases are retained.

The scripts under `scripts/` authenticate, submit batch workloads, poll them to completion, export result CSV, and calculate per-model metrics. Set credentials in the environment rather than passing them on a shared command line:

```bash
export CODEJUDGE_API_URL=http://localhost:8000/api
export CODEJUDGE_EMAIL=researcher@example.com
export CODEJUDGE_PASSWORD='your-password'

python scripts/benchmark.py --input samples.jsonl --model-name model-x --repeats 2 --out results.csv
python scripts/metrics.py --input results.csv --out metrics.csv
python scripts/load_test.py --count 120 --problem-id 1
```

`benchmark.py` accepts `--api`, `--email`, `--password`, `--input`, `--batch-name`, `--model-name`, `--repeats` (1–10), `--out`, and `--poll-interval`. Credentials may instead be supplied with `CODEJUDGE_EMAIL` and `CODEJUDGE_PASSWORD`; `CODEJUDGE_API_URL` defaults to `http://localhost:8000/api`. The script chunks requests to both item-count and request-body limits, waits until all submitted batches are terminal, and combines their authenticated CSV exports.

`metrics.py` accepts `--input` (default `results.csv`) and `--out` (default `metrics.csv`). It groups rows by `model_name` and reports pass rate, pass@1/5/10 when each problem has enough samples, verdict counts, median/P95 wall time and memory (all submissions and accepted submissions), throughput, and median queue wait. If the input contains fewer than k samples for a problem, that problem is omitted from pass@k for that k.

`load_test.py` accepts `--api`, `--email`, `--password`, `--count`, `--problem-id`, `--language`, `--batch-name`, and `--poll-interval`. It generates a synthetic mix of accepted, wrong-answer, and runtime-error solutions; it does not generate TLE/MLE cases. Run it only against an environment where you are authorized to create submissions. A 120-sample demo is also available in the UI and includes intended AC, WA, RE, TLE, and MLE examples.

Input files for the benchmark may be JSONL, JSON arrays/objects, or CSV with `problem_id`, `language_id`, and `source_code` fields; `sample_id` is optional. Shared-host timing is noisy and parallelism affects wall-clock time. Use repeats, compare medians, and report the worker/container configuration and load conditions.

## Configuration

Copy `.env.example` to `.env` for local Compose runs. Keep `.env` private and never commit real passwords, JWT secrets, or service URLs. Settings are read from environment variables; Compose passes API configuration through `.env` and worker-specific settings into the worker container. The frontend settings below are build-time values, so rebuild the frontend after changing them.

| Variable | Default | Description |
|---|---:|---|
| `APP_ENV` | `dev` | Application environment (`dev`, `prod`, or `test`) |
| `DATABASE_URL` | local PostgreSQL URL | SQLAlchemy database connection; `POSTGRES_URL` is accepted as an alias |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | `codejudge`, `postgres`, `postgres` | Compose PostgreSQL database and user configuration |
| `BROKER_URL` | local RabbitMQ URL | Celery/RabbitMQ broker connection |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis result backend, rate-limit, worker heartbeat, and capacity lease connection |
| `JWT_SECRET` | development placeholder | Signing key for access tokens; replace with a long random secret outside local development |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Access-token lifetime |
| `RATE_LIMIT_PER_MINUTE` | `60` | General API rate limit |
| `BATCH_MAX_ITEMS` | `500` | Maximum expanded submissions in one batch |
| `BATCH_RATE_PER_HOUR` | `20` | Batch creation limit per user per hour |
| `MAX_ACTIVE_SUBMISSIONS_PER_USER` | `1000` | Maximum pending plus running submissions for each user |
| `BATCH_REQUEST_MAX_BYTES` | `20971520` | Maximum HTTP batch-create request body (20 MiB) |
| `BATCH_STALE_PENDING_SECONDS` | `120` | Minimum pending age before the periodic recovery sweep republishes a task |
| `WORKER_CONCURRENCY` | CPU count, capped at `4` | Celery task concurrency on each worker instance |
| `WORKER_POOL` | `threads` for Compose/Make | Celery pool selected by the worker command; threads are recommended for Windows |
| `MAX_PARALLEL_CONTAINERS` | 2 x CPU count | Concurrent sandbox cap shared by workers with the same host ID |
| `WORKER_HOST_ID` | Hostname | Redis capacity-lease scope: same value for workers on one physical host, distinct value across hosts |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `10` / `20` | SQLAlchemy connection pool sizing per process |
| `SANDBOX_WORKDIR` | `/tmp/codejudge` | Host/worker work directory shared with sandbox containers |
| `SANDBOX_RUNTIME` | Empty | Optional Docker runtime name (must be installed on every worker host) |
| `STOP_ON_FIRST_FAIL` | `true` | Stop a submission after its first failed test |
| `FRONTEND_ORIGIN`, `CORS_ALLOW_ORIGINS` | `http://localhost:5173` | Browser origin and allowed CORS origins |
| `VITE_API_URL` | `http://localhost:8000/api` | Frontend API base URL |
| `VITE_BATCH_MAX_ITEMS` | `500` | Frontend display limit; keep aligned with `BATCH_MAX_ITEMS` |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | development defaults | Credentials used by `make seed` when creating the initial admin |

Batch item size is additionally limited to 64 KiB of UTF-8 source code, `sample_id` to 255 characters, and repeats to 1–10. Capacity is enforced per worker host, not globally across all hosts. Calculate PostgreSQL connection requirements using the total API and worker process count multiplied by each process's pool size plus overflow. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for deployment-specific capacity and queue upgrade instructions.

## Development and verification

Run backend tests, backend lint, and the frontend production type-check/build:

```bash
make test
make lint
make frontend
```

The backend's default test command excludes Docker-marked tests. To run real container tests, first build both sandbox images and ensure the test process can reach the Docker daemon:

```bash
make images
make test-docker
```

Docker integration tests exercise AC, WA, RE, TLE, and MLE verdicts, plus recovery and orphan-sandbox cleanup after a worker container is killed. The frontend unit tests use Vitest:

```bash
cd frontend
npm ci
npm test
npm run build
```

To rebuild and start the local stack from scratch:

```bash
cp .env.example .env  # only when .env does not already exist
make images
make up
make migrate
make seed
```

## Security and limitations

- Never execute submitted code on the API host or in the API process. Only sandbox containers execute solutions.
- Sandboxes have networking disabled and are configured with memory, CPU, PID, filesystem, and process limits. Expected outputs are compared outside the sandbox.
- Hidden tests remain in the database/worker and are not returned by API endpoints.
- Docker shares the host kernel. For stronger isolation, consider a supported runtime such as gVisor or a microVM design such as Firecracker.
- Wall-clock measurements include sandbox/container overhead and vary by machine; use repeats and report medians.
- Python 3 and C++17 are the currently supported languages.

## Deployment and upgrades

For production, keep the API/frontend separate from trusted worker hosts. Workers need PostgreSQL, RabbitMQ, Redis, and Docker access; do not pass API JWT or admin credentials to worker containers. Run exactly one Celery Beat service per deployment so the recovery sweeper does not run redundantly.

### Before exposing a deployment publicly

- Replace every development credential with a unique, randomly generated secret; keep secrets in the host's secret manager or a private environment file.
- Put the frontend and API behind HTTPS, and set `CORS_ALLOW_ORIGINS` to the exact frontend origin.
- Keep Docker access limited to trusted worker hosts. Anyone who can access the Docker socket can control that host.
- Back up PostgreSQL and monitor API health, queue depth, worker availability, and sandbox capacity.
- Start exactly one Beat scheduler and verify worker hosts have the required sandbox images before accepting submissions.

### Upgrade an existing deployment

Back up PostgreSQL and stop producers/consumers before performing the one-time priority-queue change. First inspect the `codejudge` queue and confirm it is drained. Deleting a non-empty queue discards its broker messages (the database retains rows, which the recovery sweeper can later republish):

```bash
docker compose stop api
docker compose --profile worker stop worker beat
docker compose exec rabbitmq rabbitmqctl list_queues name arguments messages_ready messages_unacknowledged
# Continue only after confirming codejudge has no ready or unacknowledged messages.
docker compose exec rabbitmq rabbitmqctl delete_queue codejudge
docker compose build api frontend
docker compose run --rm --no-deps api alembic upgrade head
docker compose up -d api frontend
docker compose --profile worker up -d --build worker beat
```

The queue deletion is only needed when upgrading an existing queue that was declared without priority support. The new queue declaration uses `x-max-priority=10`; interactive submissions have priority 5 and batch submissions priority 1. Do not delete the queue for normal restarts or on a fresh install. The additive batch migration advances to `20261101_0002`.

The easiest way to check service state is `docker compose ps`; API and frontend health checks should be healthy. Confirm the API responds at `/api/health`, the worker consumes the `codejudge` queue, and Beat is running once. For full deployment guidance and capacity trade-offs, see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Windows & WSL2 Troubleshooting

- **Line endings:** Git must check out repository text files with LF (Linux) line endings. CRLF files can prevent Linux Docker sandbox runner scripts from starting correctly and can surface as Runtime Error verdicts. The repository's `.gitattributes` enforces LF; in WSL, set `git config --global core.autocrlf false` and, if needed, re-normalize tracked files with `git add --renormalize .`.
- **Resource constraints:** On machines with 8 GB RAM or less, set `MAX_PARALLEL_CONTAINERS=1` in `.env` and start the host worker with `WORKER_CONCURRENCY=1`. Limiting both concurrent sandboxes and worker tasks helps prevent out-of-memory kills and swap-induced Time Limit Exceeded (TLE) verdicts.
- **Host worker workspace:** The host worker must be able to create submission directories in `SANDBOX_WORKDIR`. Docker-created `/tmp/codejudge` directories can be owned by root and unwritable by the WSL user; use a user-owned path such as `$HOME/.cache/codejudge` in `.env` for host workers.

To rebuild both sandbox images and restart the local services with those resource settings:

```bash
# Set these values in .env before starting the worker:
# MAX_PARALLEL_CONTAINERS=1
# WORKER_CONCURRENCY=1
# SANDBOX_WORKDIR=/home/<your-user>/.cache/codejudge
docker compose down
make images
make up
sleep 5
make migrate
make seed
if [ -f .venv/bin/activate ]; then source .venv/bin/activate; fi
set -a
source .env
set +a
mkdir -p "$SANDBOX_WORKDIR"
chmod 700 "$SANDBOX_WORKDIR"
make worker WORKER_POOL=threads WORKER_CONCURRENCY=1
```

`make up` already starts Compose services in detached mode and waits for health checks; do not append `-d` to the Make command. `make worker` loads the repository-root `.env` before starting Celery, so the host worker uses the same workspace and capacity settings as Compose even though it runs from `backend/`. The worker command runs in the foreground; keep that terminal open and stop it with Ctrl+C. `docker compose down` preserves named database volumes; do not add `-v` unless you intend to delete persisted data.
