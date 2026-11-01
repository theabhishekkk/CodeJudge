# CodeJudge

CodeJudge is an online judge and research harness for evaluating generated code against public samples and hidden test cases. The FastAPI API accepts submissions, RabbitMQ/Celery dispatches them to workers, and each test runs in a fresh Docker sandbox. The API never executes submitted code.

Supported languages are Python 3 and C++17. Verdicts are Accepted (`AC`), Wrong Answer (`WA`), Time Limit Exceeded (`TLE`), Memory Limit Exceeded (`MLE`), and Runtime Error (`RE`).

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

- **FastAPI** handles authentication, problems, submission requests, history, and statistics.
- **PostgreSQL** stores users, problems, test cases, submissions, and per-test metrics.
- **RabbitMQ and Celery** provide asynchronous grading. Grading tasks use the `codejudge` queue.
- **Redis** is used as the Celery result backend and for service health checks.
- **Docker** runs each untrusted solution in a short-lived, resource-limited container with networking disabled.
- **React, TypeScript, and Vite** provide registration/login, problem solving, submission polling/history, and the dashboard.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for more detail.

## Quickstart (Docker Desktop or Docker Engine)

Prerequisites: Docker with Compose, Git Bash/WSL or another Bash shell, Python 3.11 for a host worker, and Node.js/npm only if running the frontend in Vite development mode.

1. Copy the example environment file and set a private `JWT_SECRET` and admin password for any non-local deployment:

   ```bash
   cp .env.example .env
   ```

2. Build the Python and C++ sandbox images:

   ```bash
   make images
   ```

3. Build and start PostgreSQL, RabbitMQ, Redis, the API, and the Nginx-served frontend. The command waits for health checks:

   ```bash
   make up
   ```

4. Apply the database migration and add the admin account plus six sample problems:

   ```bash
   make migrate
   make seed
   ```

5. Start one grading worker. In development, the worker runs on the host so the Docker bind-mount paths are valid. Install the backend package in the Python environment first:

   ```bash
   python -m pip install -e backend
   make worker
   ```

   The worker consumes only the `codejudge` queue. On Windows, use the solo pool:

   ```bash
   make worker CELERY_POOL=--pool=solo
   ```

6. Open the application at <http://localhost:5173>. The API is at <http://localhost:8000>; interactive API documentation is at <http://localhost:8000/docs>.

`make migrate` and `make seed` execute inside the running API container; the host does not need Alembic or database client packages for those commands.

### Optional worker container

Start the optional Compose worker with:

```bash
docker compose --profile worker up -d --build worker
```

This mounts `/var/run/docker.sock` and the sandbox work directory. Docker socket access gives the worker control over the host Docker daemon (effectively root-equivalent access); use this only on a trusted, isolated machine. Do not run both the host and container worker unless you intentionally want multiple consumers.

### Vite development frontend

The Compose frontend serves the production build on port 5173. To use Vite hot reload instead, stop that service first, then run:

```bash
docker compose stop frontend
cd frontend
npm ci
npm run dev
```

Vite listens on <http://localhost:5173> and uses `VITE_API_URL`, defaulting to `http://localhost:8000/api`.

## Using the application

1. Register at `/register` or sign in at `/login`.
2. Choose a challenge from `/problems`, then open a problem such as `/problem/1`.
3. Select Python 3 or C++17, edit the starter code, and submit.
4. The submission page polls every second until grading completes. It displays the verdict, wall/CPU time, peak memory, and per-test metrics without revealing hidden inputs or expected outputs.
5. Review history at `/submissions` and runtime, memory, pass-rate, and verdict statistics at `/dashboard`.

The frontend stores the JWT access token in local storage and attaches it to authenticated API calls. Unauthorized responses sign the user out; API/network and rate-limit errors appear as notices.

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

## Seed data and research scripts

`make seed` creates the admin account using `ADMIN_EMAIL` and `ADMIN_PASSWORD` and seeds six problems with sample and hidden test cases. Set these variables in `.env` before seeding if you need different credentials.

The scripts are under `scripts/`. **The current benchmark and metrics scripts are demo stubs, not a live benchmark client:** `benchmark.py` writes two fixed example rows to `results.csv`, and `metrics.py` prints those rows. They do not authenticate, submit solutions, poll the API, or calculate research metrics yet.

```bash
python scripts/benchmark.py
python scripts/metrics.py
```

Do not use the demo output for research conclusions. For real submissions, use the API flow above; execution timing on shared hardware is noisy, so repeat samples and compare medians.

## Development and verification

```bash
make test       # Backend tests
make lint       # Ruff checks
make frontend   # Frontend TypeScript check and production build
make test-docker  # Docker-marked tests, if available
```

Docker integration tests require the sandbox images and a working Docker daemon. The current test suite does not yet include Docker-marked adversarial tests. To rebuild and start the full local stack:

```bash
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

## Production notes

Keep the API and frontend separate from worker hosts. Workers need database/broker connectivity and Docker access, but should not receive API-only secrets. Use managed PostgreSQL and a managed broker where appropriate. Configure production credentials through deployment secrets, never by committing them to the repository.
