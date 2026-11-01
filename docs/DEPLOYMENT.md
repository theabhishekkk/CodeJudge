# Deployment guide

## Recommended hosting model

- Run the FastAPI API and the frontend behind a single public-facing app node.
- Run Celery workers on a separate compute host with Docker access and a direct connection to Postgres and RabbitMQ.
- Keep secrets out of the repository and inject them as environment variables in CI/CD or cloud consoles.

## Security trade-offs

The optional worker profile binds `/var/run/docker.sock` into the container. This makes sandbox orchestration easier, but it gives the container full control over the host Docker daemon. Use it only in trusted and tightly limited environments.

## Example cloud setup

- DigitalOcean droplets for API and worker compute.
- Neon or Supabase for PostgreSQL.
- CloudAMQP or Upstash for the message broker.
- GitHub Actions for CI/CD.

## Health checklist

1. Ensure Docker daemon access is available on worker hosts.
2. Set `DATABASE_URL`, `BROKER_URL`, `REDIS_URL`, and `JWT_SECRET` in `.env` or CI secrets.
3. Run `make images && make up && make migrate && make seed`.
4. Start the worker with `make worker`.
