import asyncio
from urllib.parse import parse_qs, urlparse

import httpx
import pytest


def _insert_user(database, provider_user_id: str, provider_username: str) -> int:
    db = database.get_db()
    try:
        user_id = db.execute(
            """
            INSERT INTO users (provider, provider_user_id, provider_username)
            VALUES ('lichess', %s, %s)
            RETURNING id
            """,
            (provider_user_id, provider_username),
        ).fetchone()["id"]
        db.commit()
        return user_id
    finally:
        db.close()


def _insert_set(database, user_id: int, name: str = "Set", target_rating: int = 1500) -> int:
    db = database.get_db()
    try:
        set_id = db.execute(
            """
            INSERT INTO puzzle_sets (user_id, name, target_rating)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (user_id, name, target_rating),
        ).fetchone()["id"]
        db.commit()
        return set_id
    finally:
        db.close()


def _insert_cycle(database, set_id: int, cycle_number: int = 1) -> int:
    db = database.get_db()
    try:
        cycle_id = db.execute(
            """
            INSERT INTO cycles (set_id, cycle_number)
            VALUES (%s, %s)
            RETURNING id
            """,
            (set_id, cycle_number),
        ).fetchone()["id"]
        db.commit()
        return cycle_id
    finally:
        db.close()


def _login_client(client, auth, user_id: int) -> str:
    token = auth.create_session(user_id)
    client.cookies.set(auth.SESSION_COOKIE_NAME, token)
    return token


def test_protected_routes_require_auth(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/sets").status_code == 401


def test_oauth_start_sets_state_cookie_and_redirects(client, backend_modules):
    auth = backend_modules["auth"]

    response = client.get("/api/auth/lichess/start", follow_redirects=False)

    assert response.status_code == 302
    assert auth.AUTH_FLOW_COOKIE_NAME in client.cookies
    assert response.headers["location"].startswith("https://lichess.org/oauth")


def test_oauth_login_creates_session_and_redirects_home(client, backend_modules, monkeypatch):
    auth = backend_modules["auth"]
    database = backend_modules["database"]

    async def fake_exchange_code_for_token(code, code_verifier, redirect_uri, request):
        assert code == "good-code"
        assert code_verifier
        assert redirect_uri.endswith("/api/auth/lichess/callback")
        return "provider-token"

    async def fake_fetch_lichess_account(access_token):
        assert access_token == "provider-token"
        return {"id": "lichess-user-123", "username": "Tester"}

    monkeypatch.setattr(auth, "exchange_code_for_token", fake_exchange_code_for_token)
    monkeypatch.setattr(auth, "fetch_lichess_account", fake_fetch_lichess_account)

    start_response = client.get("/api/auth/lichess/start", follow_redirects=False)
    assert start_response.status_code == 302
    assert auth.AUTH_FLOW_COOKIE_NAME in client.cookies

    provider_redirect = urlparse(start_response.headers["location"])
    state = parse_qs(provider_redirect.query)["state"][0]

    callback_response = client.get(
        "/api/auth/lichess/callback",
        params={"code": "good-code", "state": state},
        follow_redirects=False,
    )
    assert callback_response.status_code == 302
    assert callback_response.headers["location"] == "/"
    assert auth.SESSION_COOKIE_NAME in client.cookies

    me_response = client.get("/api/me")
    assert me_response.status_code == 200
    assert me_response.json()["user"]["provider_user_id"] == "lichess-user-123"
    assert me_response.json()["user"]["provider_username"] == "Tester"

    db = database.get_db()
    try:
        session_count = db.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
        assert session_count == 1
    finally:
        db.close()


def test_invalid_oauth_state_is_rejected(client):
    start_response = client.get("/api/auth/lichess/start", follow_redirects=False)
    assert start_response.status_code == 302

    callback_response = client.get(
        "/api/auth/lichess/callback",
        params={"code": "ignored", "state": "wrong-state"},
        follow_redirects=False,
    )
    assert callback_response.status_code == 400


def test_fetch_lichess_account_sends_user_agent(backend_modules, monkeypatch):
    auth = backend_modules["auth"]
    captured = {}

    class FakeAsyncClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers):
            captured["url"] = url
            captured["headers"] = headers
            request = httpx.Request("GET", url)
            return httpx.Response(
                200,
                json={"id": "lichess-user-123", "username": "Tester"},
                request=request,
            )

    monkeypatch.setattr(auth.httpx, "AsyncClient", FakeAsyncClient)

    account = asyncio.run(auth.fetch_lichess_account("provider-token"))

    assert account == {"id": "lichess-user-123", "username": "Tester"}
    assert captured["timeout"] == 15.0
    assert captured["url"] == "https://lichess.org/api/account"
    assert captured["headers"]["Authorization"] == "Bearer provider-token"
    assert captured["headers"]["User-Agent"] == auth.LICHESS_USER_AGENT


def test_fetch_lichess_account_reports_lichess_rate_limit(backend_modules, monkeypatch):
    auth = backend_modules["auth"]

    class FakeAsyncClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers):
            request = httpx.Request("GET", url)
            return httpx.Response(429, json={"error": "Too Many Requests"}, request=request)

    monkeypatch.setattr(auth.httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(auth.HTTPException) as exc_info:
        asyncio.run(auth.fetch_lichess_account("provider-token"))

    assert exc_info.value.status_code == 429
    assert "wait at least one minute" in exc_info.value.detail


def test_sets_are_scoped_to_current_user(client, backend_modules):
    database = backend_modules["database"]
    auth = backend_modules["auth"]

    owner_id = _insert_user(database, "owner-id", "Owner")
    other_id = _insert_user(database, "other-id", "Other")
    _insert_set(database, owner_id, name="Owner Set")
    _insert_set(database, other_id, name="Other Set")

    _login_client(client, auth, owner_id)
    response = client.get("/api/sets")

    assert response.status_code == 200
    payload = response.json()
    assert [row["name"] for row in payload] == ["Owner Set"]


def test_other_user_cannot_access_foreign_resources(client, backend_modules):
    database = backend_modules["database"]
    auth = backend_modules["auth"]

    owner_id = _insert_user(database, "owner-id", "Owner")
    intruder_id = _insert_user(database, "intruder-id", "Intruder")
    set_id = _insert_set(database, owner_id, name="Private Set")
    cycle_id = _insert_cycle(database, set_id)

    _login_client(client, auth, intruder_id)

    assert client.get(f"/api/sets/{set_id}").status_code == 404
    assert client.patch(f"/api/cycles/{cycle_id}/finish").status_code == 404


def test_logout_revokes_session(client, backend_modules):
    database = backend_modules["database"]
    auth = backend_modules["auth"]

    user_id = _insert_user(database, "logout-id", "LogoutUser")
    _login_client(client, auth, user_id)

    logout_response = client.post("/api/logout")
    assert logout_response.status_code == 200
    assert client.get("/api/me").status_code == 401
