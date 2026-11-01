# CodeJudge: standing rules
- Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic, Celery, RabbitMQ, Redis, PostgreSQL, Docker SDK for Python. Frontend: React + Vite + TypeScript.
- NEVER execute untrusted/submitted code on the host or in the API process. Only inside sandbox containers.
- Never log or return hidden test inputs/expected outputs to API clients.
- All config via environment variables (.env.example). No secrets in git.
- Every module gets type hints; every feature gets pytest tests.
- After each phase: run tests, fix failures, then `git add -A && git commit -m "<phase>"`.
- Prefer small, readable files. Keep README.md current.