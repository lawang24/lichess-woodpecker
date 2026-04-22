import importlib
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row


def _load_database_url() -> str | None:
    direct = os.environ.get("DATABASE_URL")
    if direct:
        return direct

    repo_root = Path(__file__).resolve().parents[2]
    env_paths = (
        repo_root / ".env",
        repo_root / ".env.local",
        repo_root / "backend" / ".env",
        repo_root / "backend" / ".env.local",
    )
    for env_path in env_paths:
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == "DATABASE_URL":
                return value.strip().strip("'\"")
    return None


def _database_url_with_schema(base_url: str, schema_name: str) -> str:
    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema_name}"
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def _import_backend_module(module_name: str):
    candidates = (f"backend.{module_name}", module_name)
    for candidate in candidates:
        try:
            return importlib.import_module(candidate)
        except ModuleNotFoundError:
            continue
    raise ModuleNotFoundError(module_name)


@pytest.fixture
def backend_modules(monkeypatch):
    base_database_url = _load_database_url()
    if not base_database_url:
        pytest.skip("DATABASE_URL is required to run backend auth tests")

    schema_name = f"test_auth_{uuid.uuid4().hex}"
    with psycopg.connect(base_database_url, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{schema_name}"')

    monkeypatch.setenv("DATABASE_URL", base_database_url)
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("APP_BASE_URL", "http://testserver")
    monkeypatch.setenv("LICHESS_CLIENT_ID", "test-lichess-client")
    monkeypatch.delenv("BOOTSTRAP_LICHESS_USERNAME", raising=False)
    monkeypatch.delenv("FRONTEND_DEV_URL", raising=False)
    monkeypatch.delenv("CHESS_COM_USERNAME", raising=False)

    for module_name in ("backend.main", "backend.auth", "backend.database", "main", "auth", "database"):
        if module_name in sys.modules:
            del sys.modules[module_name]

    database = _import_backend_module("database")
    auth = _import_backend_module("auth")
    main = _import_backend_module("main")
    importlib.reload(database)
    importlib.reload(auth)
    importlib.reload(main)

    def get_db_in_schema():
        conn = psycopg.connect(base_database_url, row_factory=dict_row)
        conn.execute(f'SET search_path TO "{schema_name}"')
        return conn

    def init_db_in_schema():
        with psycopg.connect(base_database_url, row_factory=dict_row) as conn:
            conn.execute(f'SET search_path TO "{schema_name}"')
            conn.execute(database.SCHEMA_PATH.read_text())

    database.close_db()
    monkeypatch.setattr(database, "get_db", get_db_in_schema)
    monkeypatch.setattr(database, "init_db", init_db_in_schema)
    monkeypatch.setattr(auth, "get_db", get_db_in_schema)
    monkeypatch.setattr(main, "get_db", get_db_in_schema)
    monkeypatch.setattr(main, "init_db", init_db_in_schema)

    try:
        yield {"database": database, "auth": auth, "main": main, "schema_name": schema_name}
    finally:
        database.close_db()
        with psycopg.connect(base_database_url, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')


@pytest.fixture
def client(backend_modules):
    with TestClient(backend_modules["main"].app) as test_client:
        yield test_client
