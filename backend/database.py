import os
from pathlib import Path
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

SCHEMA_PATH = Path(__file__).resolve().with_name("schema.sql")
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
ENV_PATHS = (
    BACKEND_DIR / ".env",
    BACKEND_DIR / ".env.local",
    PROJECT_ROOT / ".env",
    PROJECT_ROOT / ".env.local",
)
ORIGINAL_ENV_KEYS = set(os.environ)
DB_POOL_MIN_SIZE = int(os.environ.get("DB_POOL_MIN_SIZE", "1"))
DB_POOL_MAX_SIZE = max(DB_POOL_MIN_SIZE, int(os.environ.get("DB_POOL_MAX_SIZE", "5")))
_db_pool: ConnectionPool | None = None


def _load_env_files() -> None:
    for env_path in ENV_PATHS:
        if not env_path.exists():
            continue

        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key in ORIGINAL_ENV_KEYS:
                continue
            os.environ[key] = value.strip().strip("'\"")


_load_env_files()


def get_database_url() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return database_url

    raise RuntimeError(
        "DATABASE_URL is required, for example: "
        "postgresql://postgres:<password>@127.0.0.1:5432/postgres"
    )


class PooledConnection:
    def __init__(self, pool: ConnectionPool, conn):
        self._pool = pool
        self._conn = conn

    def __getattr__(self, name: str) -> Any:
        conn = self._require_conn()
        return getattr(conn, name)

    def __enter__(self):
        self._require_conn()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        conn = self._conn
        if conn is None:
            return

        try:
            if exc_type is None:
                conn.commit()
            else:
                conn.rollback()
        finally:
            self.close()

    def close(self) -> None:
        conn = self._conn
        if conn is None:
            return

        self._conn = None
        try:
            conn.rollback()
        except Exception:
            pass
        self._pool.putconn(conn)

    def _require_conn(self):
        if self._conn is None:
            raise RuntimeError("Database connection has already been released to the pool")
        return self._conn


def _get_db_pool() -> ConnectionPool:
    global _db_pool
    if _db_pool is None:
        _db_pool = ConnectionPool(
            conninfo=get_database_url(),
            kwargs={"row_factory": dict_row},
            min_size=DB_POOL_MIN_SIZE,
            max_size=DB_POOL_MAX_SIZE,
        )
    return _db_pool


def get_db():
    pool = _get_db_pool()
    return PooledConnection(pool, pool.getconn())


def init_db() -> None:
    pool = _get_db_pool()
    pool.wait()
    with pool.connection() as conn:
        conn.execute(SCHEMA_PATH.read_text())


def close_db() -> None:
    global _db_pool
    if _db_pool is None:
        return

    _db_pool.close()
    _db_pool = None
