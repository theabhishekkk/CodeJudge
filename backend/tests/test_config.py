from __future__ import annotations

from codejudge.core.config import Settings


def test_database_url_accepts_postgres_url_alias() -> None:
    database_url = "postgresql+psycopg://user:password@database:5432/codejudge"
    settings = Settings(_env_file=None, POSTGRES_URL=database_url)

    assert settings.DATABASE_URL == database_url


def test_batch_and_worker_settings_have_safe_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.BATCH_MAX_ITEMS == 500
    assert settings.BATCH_RATE_PER_HOUR == 20
    assert settings.MAX_ACTIVE_SUBMISSIONS_PER_USER == 1000
    assert settings.BATCH_REQUEST_MAX_BYTES == 20 * 1024 * 1024
    assert settings.BATCH_STALE_PENDING_SECONDS == 120
    assert settings.WORKER_CONCURRENCY >= 1
    assert settings.MAX_PARALLEL_CONTAINERS >= 1
