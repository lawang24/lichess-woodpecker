import os
from pathlib import Path

from psycopg import connect
from psycopg.rows import dict_row

SCHEMA_PATH = Path(__file__).resolve().with_name("schema.sql")
ENV_PATHS = (
    Path(__file__).resolve().parent.parent / ".env",
    Path(__file__).resolve().parent.parent / ".env.local",
)


def _load_env_files() -> None:
    for env_path in ENV_PATHS:
        if not env_path.exists():
            continue

        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_env_files()


def get_database_url() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return database_url

    raise RuntimeError(
        "DATABASE_URL is required, for example: "
        "postgresql://postgres:<password>@127.0.0.1:5432/postgres"
    )


def get_db():
    return connect(get_database_url(), row_factory=dict_row)


def init_db() -> None:
    with get_db() as conn:
        conn.execute(SCHEMA_PATH.read_text())
