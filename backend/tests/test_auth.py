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


def _insert_puzzle_item(
    database,
    set_id: int,
    puzzle_id: str,
    position: int = 0,
    rating: int = 1500,
) -> int:
    db = database.get_db()
    try:
        item_id = db.execute(
            """
            INSERT INTO puzzle_set_items (set_id, puzzle_id, rating, position)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (set_id, puzzle_id, rating, position),
        ).fetchone()["id"]
        db.commit()
        return item_id
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


def test_completion_requires_puzzle_in_cycle_set(client, backend_modules):
    database = backend_modules["database"]
    auth = backend_modules["auth"]

    user_id = _insert_user(database, "completion-owner-id", "CompletionOwner")
    active_set_id = _insert_set(database, user_id, name="Active Set")
    other_set_id = _insert_set(database, user_id, name="Other Set")
    active_item_id = _insert_puzzle_item(database, active_set_id, "active-puzzle")
    _insert_puzzle_item(database, other_set_id, "other-puzzle")
    cycle_id = _insert_cycle(database, active_set_id)

    _login_client(client, auth, user_id)

    rejected_response = client.post(
        f"/api/cycles/{cycle_id}/complete/other-puzzle",
        json={"solved": False},
    )
    assert rejected_response.status_code == 404
    assert rejected_response.json()["detail"] == "Puzzle not found in cycle set"

    accepted_response = client.post(
        f"/api/cycles/{cycle_id}/complete/active-puzzle",
        json={"solved": True},
    )
    assert accepted_response.status_code == 200

    cycle_response = client.get(f"/api/cycles/{cycle_id}")
    assert cycle_response.status_code == 200
    assert cycle_response.json()["puzzles"] == [
        {
            "id": active_item_id,
            "set_id": active_set_id,
            "puzzle_id": "active-puzzle",
            "rating": 1500,
            "position": 0,
            "completed": True,
            "completed_at": cycle_response.json()["puzzles"][0]["completed_at"],
            "solved": True,
            "previous_solved": None,
        }
    ]

    db = database.get_db()
    try:
        completions = db.execute(
            """
            SELECT cycle_id, set_id, puzzle_id, solved
            FROM puzzle_completions
            ORDER BY puzzle_id
            """
        ).fetchall()
    finally:
        db.close()

    assert completions == [
        {
            "cycle_id": cycle_id,
            "set_id": active_set_id,
            "puzzle_id": "active-puzzle",
            "solved": True,
        }
    ]


def test_completion_requires_solved_body(client, backend_modules):
    database = backend_modules["database"]
    auth = backend_modules["auth"]

    user_id = _insert_user(database, "completion-body-id", "CompletionBody")
    set_id = _insert_set(database, user_id, name="Body Set")
    _insert_puzzle_item(database, set_id, "body-puzzle")
    cycle_id = _insert_cycle(database, set_id)

    _login_client(client, auth, user_id)

    response = client.post(f"/api/cycles/{cycle_id}/complete/body-puzzle")
    assert response.status_code == 422

    db = database.get_db()
    try:
        completion_count = db.execute(
            "SELECT COUNT(*) AS n FROM puzzle_completions"
        ).fetchone()["n"]
    finally:
        db.close()

    assert completion_count == 0


def test_finish_cycle_counts_solved_completed_puzzles(client, backend_modules):
    database = backend_modules["database"]
    auth = backend_modules["auth"]

    user_id = _insert_user(database, "solved-count-id", "SolvedCount")
    set_id = _insert_set(database, user_id, name="Solved Count Set")
    _insert_puzzle_item(database, set_id, "solved-puzzle", position=0)
    _insert_puzzle_item(database, set_id, "missed-puzzle", position=1)
    cycle_id = _insert_cycle(database, set_id)

    _login_client(client, auth, user_id)

    solved_response = client.post(
        f"/api/cycles/{cycle_id}/complete/solved-puzzle",
        json={"solved": True},
    )
    missed_response = client.post(
        f"/api/cycles/{cycle_id}/complete/missed-puzzle",
        json={"solved": False},
    )
    assert solved_response.status_code == 200
    assert missed_response.status_code == 200

    cycle_response = client.get(f"/api/cycles/{cycle_id}")
    assert cycle_response.status_code == 200
    assert {
        puzzle["puzzle_id"]: puzzle["solved"]
        for puzzle in cycle_response.json()["puzzles"]
    } == {
        "solved-puzzle": True,
        "missed-puzzle": False,
    }

    finish_response = client.patch(f"/api/cycles/{cycle_id}/finish")
    assert finish_response.status_code == 200
    assert finish_response.json()["completed_count"] == 2
    assert finish_response.json()["solved_count"] == 1

    history_response = client.get(f"/api/sets/{set_id}/history")
    assert history_response.status_code == 200
    assert history_response.json()["cycles"][0]["completed_count"] == 2
    assert history_response.json()["cycles"][0]["solved_count"] == 1


def test_cycle_detail_includes_previous_cycle_results(client, backend_modules):
    database = backend_modules["database"]
    auth = backend_modules["auth"]

    user_id = _insert_user(database, "previous-result-id", "PreviousResult")
    set_id = _insert_set(database, user_id, name="Previous Result Set")
    _insert_puzzle_item(database, set_id, "previous-solved", position=0)
    _insert_puzzle_item(database, set_id, "previous-missed", position=1)
    _insert_puzzle_item(database, set_id, "previous-unseen", position=2)
    first_cycle_id = _insert_cycle(database, set_id, cycle_number=1)
    second_cycle_id = _insert_cycle(database, set_id, cycle_number=2)

    _login_client(client, auth, user_id)

    assert client.post(
        f"/api/cycles/{first_cycle_id}/complete/previous-solved",
        json={"solved": True},
    ).status_code == 200
    assert client.post(
        f"/api/cycles/{first_cycle_id}/complete/previous-missed",
        json={"solved": False},
    ).status_code == 200

    first_cycle_response = client.get(f"/api/cycles/{first_cycle_id}")
    assert first_cycle_response.status_code == 200
    assert {
        puzzle["puzzle_id"]: puzzle["previous_solved"]
        for puzzle in first_cycle_response.json()["puzzles"]
    } == {
        "previous-solved": None,
        "previous-missed": None,
        "previous-unseen": None,
    }

    second_cycle_response = client.get(f"/api/cycles/{second_cycle_id}")
    assert second_cycle_response.status_code == 200
    assert {
        puzzle["puzzle_id"]: {
            "completed": puzzle["completed"],
            "solved": puzzle["solved"],
            "previous_solved": puzzle["previous_solved"],
        }
        for puzzle in second_cycle_response.json()["puzzles"]
    } == {
        "previous-solved": {
            "completed": False,
            "solved": None,
            "previous_solved": True,
        },
        "previous-missed": {
            "completed": False,
            "solved": None,
            "previous_solved": False,
        },
        "previous-unseen": {
            "completed": False,
            "solved": None,
            "previous_solved": None,
        },
    }


def test_replace_puzzle_removes_old_item_and_completions(client, backend_modules, monkeypatch):
    database = backend_modules["database"]
    auth = backend_modules["auth"]
    main = backend_modules["main"]

    user_id = _insert_user(database, "replace-owner-id", "ReplaceOwner")
    set_id = _insert_set(database, user_id, name="Replace Set", target_rating=1600)
    _insert_puzzle_item(database, set_id, "keep-puzzle", position=0, rating=1500)
    old_item_id = _insert_puzzle_item(database, set_id, "old-puzzle", position=1, rating=1400)
    first_cycle_id = _insert_cycle(database, set_id, cycle_number=1)
    second_cycle_id = _insert_cycle(database, set_id, cycle_number=2)

    class FakeCatalog:
        def sample_replacement(self, rating, excluded_puzzle_ids):
            assert rating == 1600
            assert excluded_puzzle_ids == {"keep-puzzle", "old-puzzle"}
            return {"puzzle_id": "new-puzzle", "rating": 1610}

    monkeypatch.setattr(main, "_get_puzzle_catalog", lambda: FakeCatalog())
    _login_client(client, auth, user_id)

    assert client.post(
        f"/api/cycles/{first_cycle_id}/complete/old-puzzle",
        json={"solved": True},
    ).status_code == 200
    assert client.patch(f"/api/cycles/{first_cycle_id}/finish").status_code == 200
    assert client.post(
        f"/api/cycles/{second_cycle_id}/complete/old-puzzle",
        json={"solved": False},
    ).status_code == 200

    response = client.post(f"/api/cycles/{second_cycle_id}/replace/old-puzzle")

    assert response.status_code == 200
    assert response.json() == {
        "id": response.json()["id"],
        "set_id": set_id,
        "puzzle_id": "new-puzzle",
        "rating": 1610,
        "position": 1,
        "completed": False,
        "completed_at": None,
        "solved": None,
        "previous_solved": None,
    }

    db = database.get_db()
    try:
        items = db.execute(
            """
            SELECT id, puzzle_id, rating, position
            FROM puzzle_set_items
            WHERE set_id = %s
            ORDER BY position, puzzle_id
            """,
            (set_id,),
        ).fetchall()
        old_completion_count = db.execute(
            """
            SELECT COUNT(*) AS n
            FROM puzzle_completions
            WHERE set_id = %s AND puzzle_id = %s
            """,
            (set_id, "old-puzzle"),
        ).fetchone()["n"]
        first_cycle = db.execute(
            """
            SELECT completed_count, solved_count
            FROM cycles
            WHERE id = %s
            """,
            (first_cycle_id,),
        ).fetchone()
    finally:
        db.close()

    assert items == [
        {"id": items[0]["id"], "puzzle_id": "keep-puzzle", "rating": 1500, "position": 0},
        {"id": items[1]["id"], "puzzle_id": "new-puzzle", "rating": 1610, "position": 1},
    ]
    assert old_item_id not in {item["id"] for item in items}
    assert old_completion_count == 0
    assert first_cycle == {"completed_count": 0, "solved_count": 0}

    cycle_response = client.get(f"/api/cycles/{second_cycle_id}")
    assert cycle_response.status_code == 200
    assert [puzzle["puzzle_id"] for puzzle in cycle_response.json()["puzzles"]] == [
        "keep-puzzle",
        "new-puzzle",
    ]
    assert cycle_response.json()["puzzles"][1]["completed"] is False


def test_replace_puzzle_rejects_finished_cycle_and_missing_puzzle(client, backend_modules):
    database = backend_modules["database"]
    auth = backend_modules["auth"]

    user_id = _insert_user(database, "replace-reject-id", "ReplaceReject")
    set_id = _insert_set(database, user_id, name="Replace Reject Set")
    _insert_puzzle_item(database, set_id, "finished-puzzle", position=0)
    finished_cycle_id = _insert_cycle(database, set_id, cycle_number=1)
    active_cycle_id = _insert_cycle(database, set_id, cycle_number=2)

    _login_client(client, auth, user_id)

    assert client.patch(f"/api/cycles/{finished_cycle_id}/finish").status_code == 200

    finished_response = client.post(
        f"/api/cycles/{finished_cycle_id}/replace/finished-puzzle"
    )
    missing_response = client.post(
        f"/api/cycles/{active_cycle_id}/replace/missing-puzzle"
    )

    assert finished_response.status_code == 400
    assert finished_response.json()["detail"] == "Cycle already finished"
    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == "Puzzle not found in cycle set"


def test_schema_migrates_existing_cycle_completions_table(backend_modules):
    database = backend_modules["database"]
    database.init_db()

    user_id = _insert_user(database, "migration-owner-id", "MigrationOwner")
    set_id = _insert_set(database, user_id, name="Migrated Set")
    _insert_puzzle_item(database, set_id, "migrated-puzzle")
    cycle_id = _insert_cycle(database, set_id)

    db = database.get_db()
    try:
        db.execute("DROP TABLE puzzle_completions")
        db.execute(
            """
            CREATE TABLE cycle_completions (
                cycle_id BIGINT NOT NULL REFERENCES cycles(id) ON DELETE CASCADE,
                puzzle_id TEXT NOT NULL,
                completed_at DOUBLE PRECISION NOT NULL,
                PRIMARY KEY (cycle_id, puzzle_id)
            )
            """
        )
        db.execute(
            """
            CREATE INDEX cycle_completions_cycle_idx
                ON cycle_completions (cycle_id)
            """
        )
        db.execute(
            """
            INSERT INTO cycle_completions (cycle_id, puzzle_id, completed_at)
            VALUES (%s, %s, %s)
            """,
            (cycle_id, "migrated-puzzle", 123.456),
        )

        db.execute(database.SCHEMA_PATH.read_text())

        table_names = db.execute(
            """
            SELECT
                to_regclass('cycle_completions') AS old_name,
                to_regclass('puzzle_completions') AS new_name
            """
        ).fetchone()
        migrated_completion = db.execute(
            """
            SELECT cycle_id, set_id, puzzle_id, completed_at, solved
            FROM puzzle_completions
            """
        ).fetchone()
        constraints = db.execute(
            """
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'puzzle_completions'::regclass
              AND conname IN (
                  'puzzle_completions_cycle_set_fkey',
                  'puzzle_completions_pkey',
                  'puzzle_completions_set_puzzle_fkey'
              )
            ORDER BY conname
            """
        ).fetchall()
        db.commit()
    finally:
        db.close()

    assert table_names["old_name"] is None
    assert str(table_names["new_name"]) == "puzzle_completions"
    assert migrated_completion == {
        "cycle_id": cycle_id,
        "set_id": set_id,
        "puzzle_id": "migrated-puzzle",
        "completed_at": 123.456,
        "solved": False,
    }
    assert [constraint["conname"] for constraint in constraints] == [
        "puzzle_completions_cycle_set_fkey",
        "puzzle_completions_pkey",
        "puzzle_completions_set_puzzle_fkey",
    ]


def test_cycle_creation_is_capped_and_reset_restarts(client, backend_modules):
    database = backend_modules["database"]
    auth = backend_modules["auth"]

    user_id = _insert_user(database, "cycle-cap-id", "CycleCap")
    set_id = _insert_set(database, user_id)
    for cycle_number in range(1, 7):
        _insert_cycle(database, set_id, cycle_number)

    _login_client(client, auth, user_id)

    capped_response = client.post(f"/api/sets/{set_id}/cycles")
    assert capped_response.status_code == 400
    assert "All scheduled Woodpecker cycles" in capped_response.json()["detail"]

    reset_response = client.post(f"/api/sets/{set_id}/reset")
    assert reset_response.status_code == 200

    restart_response = client.post(f"/api/sets/{set_id}/cycles")
    assert restart_response.status_code == 200
    assert restart_response.json()["cycle_number"] == 1


def test_logout_revokes_session(client, backend_modules):
    database = backend_modules["database"]
    auth = backend_modules["auth"]

    user_id = _insert_user(database, "logout-id", "LogoutUser")
    _login_client(client, auth, user_id)

    logout_response = client.post("/api/logout")
    assert logout_response.status_code == 200
    assert client.get("/api/me").status_code == 401
