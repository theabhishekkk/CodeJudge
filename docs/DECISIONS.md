# Design decisions

- The worker never mounts expected outputs into the sandbox. Instead, they remain in the worker memory and are compared after the run. This avoids leaking hidden answers into the container and reduces attack surface.
- The dev environment runs the Celery worker on the host, not in Docker, so host paths remain valid for bind mounts and sandbox volumes.
- Docker socket access is intentionally limited to the optional worker profile; it grants the worker root-equivalent control over the host docker daemon and should only be used in trusted environments.
- For API-side security, the platform keeps hidden test data out of response payloads and logs by default.
- Batch metadata is stored separately from submissions; `submissions.batch_id` stays nullable so the existing single-submission path and historic rows remain unchanged.
- Repeated batch items use zero-based `repeat_index` values, and `queued_at` is set when the submission is created so queue-wait measurements include broker delay.
- Batch and worker capacity limits are configurable through environment-backed settings, with conservative defaults and a worker-side container limit independent of Celery concurrency.
- Container capacity uses renewable Redis leases scoped by `WORKER_HOST_ID`, so threads and prefork processes share one host limit; the worker heartbeat separately lets the sweeper distinguish live execution from a lost worker.
