# Design decisions

- The worker never mounts expected outputs into the sandbox. Instead, they remain in the worker memory and are compared after the run. This avoids leaking hidden answers into the container and reduces attack surface.
- The dev environment runs the Celery worker on the host, not in Docker, so host paths remain valid for bind mounts and sandbox volumes.
- Docker socket access is intentionally limited to the optional worker profile; it grants the worker root-equivalent control over the host docker daemon and should only be used in trusted environments.
- For API-side security, the platform keeps hidden test data out of response payloads and logs by default.
