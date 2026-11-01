from __future__ import annotations

from codejudge.core.config import Settings


def test_database_url_accepts_postgres_url_alias() -> None:
    database_url = "postgresql+psycopg://user:password@database:5432/codejudge"
    settings = Settings(_env_file=None, POSTGRES_URL=database_url)

    assert settings.DATABASE_URL == database_url
