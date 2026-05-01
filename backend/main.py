import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from psycopg import errors
from pydantic import BaseModel

try:
    from . import auth as auth_module
    from .database import close_db, get_db, init_db
    from .puzzle_catalog import CatalogNotBuiltError, PuzzleCatalog
except ImportError:
    import auth as auth_module
    from database import close_db, get_db, init_db
    from puzzle_catalog import CatalogNotBuiltError, PuzzleCatalog

BACKEND_DIR = os.path.abspath(os.path.dirname(__file__))
FRONTEND_DIST = os.path.join(BACKEND_DIR, "static")
FRONTEND_DEV_URL = os.environ.get("FRONTEND_DEV_URL", "").rstrip("/")
WOODPECKER_CYCLE_COUNT = 6
TIMESTAMP_FIELDS = {
    "created_at",
    "started_at",
    "completed_at",
    "expires_at",
    "last_seen_at",
    "revoked_at",
}
logger = logging.getLogger("uvicorn.error")
_puzzle_catalog = None


class CompletePuzzleRequest(BaseModel):
    solved: bool


def _as_utc_datetime(value):
    if value is None:
        return None
    if isinstance(value, str):
        if value.endswith("Z"):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return datetime.fromisoformat(value)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc_dict(row) -> dict:
    data = dict(row)
    for key in TIMESTAMP_FIELDS:
        value = data.get(key)
        if value is not None:
            data[key] = _as_utc_datetime(value).isoformat().replace("+00:00", "Z")
    return data


def _resolve_frontend_file(full_path: str) -> str | None:
    candidate = os.path.abspath(os.path.join(FRONTEND_DIST, full_path))
    static_root = os.path.abspath(FRONTEND_DIST)
    if os.path.commonpath([candidate, static_root]) != static_root:
        return None
    if os.path.isfile(candidate):
        return candidate
    return None


def _truncate_for_log(value: str, limit: int = 80) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


def _get_puzzle_catalog() -> PuzzleCatalog:
    global _puzzle_catalog

    if _puzzle_catalog is None:
        _puzzle_catalog = PuzzleCatalog.load()

    return _puzzle_catalog


def _load_owned_set(db, set_id: int, user_id: int):
    puzzle_set = db.execute(
        """
        SELECT *
        FROM puzzle_sets
        WHERE id = %s AND user_id = %s
        """,
        (set_id, user_id),
    ).fetchone()
    if not puzzle_set:
        raise HTTPException(404, "Set not found")
    return puzzle_set


def _load_owned_cycle(db, cycle_id: int, user_id: int):
    cycle = db.execute(
        """
        SELECT c.*
        FROM cycles c
        JOIN puzzle_sets s ON s.id = c.set_id
        WHERE c.id = %s AND s.user_id = %s
        """,
        (cycle_id, user_id),
    ).fetchone()
    if not cycle:
        raise HTTPException(404, "Cycle not found")
    return cycle


def _refresh_finished_cycle_counts(db, set_id: int) -> None:
    db.execute(
        """
        UPDATE cycles c
        SET completed_count = counts.completed_count,
            solved_count = counts.solved_count
        FROM (
            SELECT
                c.id,
                COUNT(pc.puzzle_id) AS completed_count,
                COUNT(pc.puzzle_id) FILTER (WHERE pc.solved) AS solved_count
            FROM cycles c
            LEFT JOIN puzzle_completions pc ON pc.cycle_id = c.id
            WHERE c.set_id = %s
            GROUP BY c.id
        ) counts
        WHERE c.id = counts.id
          AND c.completed_at IS NOT NULL
        """,
        (set_id,),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    auth_module.validate_auth_configuration()
    init_db()
    try:
        yield
    finally:
        close_db()


app = FastAPI(lifespan=lifespan)

if not FRONTEND_DEV_URL and os.path.isdir(FRONTEND_DIST):
    app.mount(
        "/assets",
        StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")),
        name="assets",
    )


@app.get("/api/auth/{provider}/start")
async def auth_start(provider: str, request: Request):
    authorization_url, flow_payload = auth_module.build_authorization_url(provider, request)
    response = RedirectResponse(authorization_url, status_code=302)
    auth_module.set_auth_flow_cookie(response, request, flow_payload)
    return response


@app.get("/api/auth/{provider}/callback")
async def auth_callback(provider: str, request: Request):
    auth_module.get_provider(provider)
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        raise HTTPException(400, "Missing OAuth callback parameters")

    flow = auth_module.read_auth_flow(request, provider)
    if flow.get("state") != state:
        raise HTTPException(400, "Invalid OAuth state")

    redirect_uri = auth_module.get_redirect_uri(request, provider)
    access_token = await auth_module.exchange_code_for_token(
        code,
        flow["code_verifier"],
        redirect_uri,
        request,
    )
    if provider != auth_module.LICHESS_PROVIDER:
        raise HTTPException(404, "Provider not found")

    account = await auth_module.fetch_lichess_account(access_token)
    user = auth_module.upsert_user(
        provider=provider,
        provider_user_id=account["id"],
        provider_username=account["username"],
    )
    session_token = auth_module.create_session(user["id"])

    response = RedirectResponse("/", status_code=302)
    auth_module.clear_auth_flow_cookie(response)
    auth_module.set_session_cookie(response, request, session_token)
    return response


@app.get("/api/me")
async def get_me(current_user=Depends(auth_module.require_current_user)):
    return {"user": _utc_dict(current_user)}


@app.post("/api/logout")
async def logout(request: Request):
    auth_module.revoke_session(request.cookies.get(auth_module.SESSION_COOKIE_NAME))
    response = JSONResponse({"ok": True})
    auth_module.clear_session_cookie(response)
    return response


@app.get("/api/sets")
async def list_sets(current_user=Depends(auth_module.require_current_user)):
    db = get_db()
    try:
        sets = db.execute(
            """
            SELECT
                s.id,
                s.name,
                s.target_rating,
                s.created_at,
                COUNT(i.id) AS puzzle_count
            FROM puzzle_sets s
            LEFT JOIN puzzle_set_items i ON i.set_id = s.id
            WHERE s.user_id = %s
            GROUP BY s.id, s.name, s.target_rating, s.created_at
            ORDER BY s.created_at DESC
            """,
            (current_user["id"],),
        ).fetchall()
        cycles = db.execute(
            """
            SELECT c.id, c.set_id, c.cycle_number, c.started_at, c.completed_at
            FROM cycles c
            JOIN puzzle_sets s ON s.id = c.set_id
            WHERE s.user_id = %s
            ORDER BY c.cycle_number
            """,
            (current_user["id"],),
        ).fetchall()
    finally:
        db.close()

    cycles_by_set = {}
    for cycle in cycles:
        cycle_dict = _utc_dict(cycle)
        cycles_by_set.setdefault(cycle_dict["set_id"], []).append(cycle_dict)

    result = []
    for puzzle_set in sets:
        puzzle_set_dict = _utc_dict(puzzle_set)
        puzzle_set_dict["cycles"] = cycles_by_set.get(puzzle_set_dict["id"], [])
        result.append(puzzle_set_dict)
    return result


@app.get("/api/sets/{set_id}")
async def get_set(set_id: int, current_user=Depends(auth_module.require_current_user)):
    db = get_db()
    try:
        puzzle_set = _load_owned_set(db, set_id, current_user["id"])
        items = db.execute(
            "SELECT * FROM puzzle_set_items WHERE set_id = %s ORDER BY position",
            (set_id,),
        ).fetchall()
    finally:
        db.close()
    return {"set": _utc_dict(puzzle_set), "puzzles": [dict(item) for item in items]}


@app.post("/api/sets")
async def create_set(
    request: Request,
    current_user=Depends(auth_module.require_current_user),
):
    request_started_at = time.perf_counter()
    phase = "request start"
    db = None
    name = "Untitled Set"
    count = None
    target_rating = None

    def elapsed_ms() -> float:
        return (time.perf_counter() - request_started_at) * 1000

    try:
        phase = "request body parse"
        body = await request.json()
        name = body.get("name", "Untitled Set")
        count = int(body.get("count", 50))
        rating = body.get("rating")
        target_rating = int(rating) if rating is not None else None
        logger.info(
            "create_set started name=%r count=%s rating=%s user_id=%s",
            _truncate_for_log(name),
            count,
            target_rating,
            current_user["id"],
        )

        phase = "puzzle catalog load"
        try:
            catalog = _get_puzzle_catalog()
        except CatalogNotBuiltError as exc:
            raise HTTPException(503, str(exc)) from exc

        phase = "puzzle sampling"
        if target_rating is not None:
            sample = catalog.sample_by_rating(count, target_rating)
        else:
            sample = catalog.sample_random(count)

        phase = "database connection"
        db = get_db()

        phase = "set insert"
        set_id = db.execute(
            """
            INSERT INTO puzzle_sets (user_id, name, target_rating)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (current_user["id"], name, target_rating),
        ).fetchone()["id"]

        phase = "set item bulk insert"
        if sample:
            values_sql = ", ".join(["(%s, %s, %s, %s)"] * len(sample))
            params = []
            for index, row in enumerate(sample):
                params.extend((set_id, row["puzzle_id"], int(row["rating"]), index))
            db.execute(
                f"""
                INSERT INTO puzzle_set_items (set_id, puzzle_id, rating, position)
                VALUES {values_sql}
                """,
                params,
            )

        phase = "commit"
        db.commit()
        logger.info(
            "create_set completed id=%s user_id=%s name=%r requested=%s actual=%s total=%.1fms",
            set_id,
            current_user["id"],
            _truncate_for_log(name),
            count,
            len(sample),
            elapsed_ms(),
        )
        return {"id": set_id, "name": name, "count": len(sample)}
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "create_set failed during %s after %.1fms name=%r count=%s rating=%s user_id=%s",
            phase,
            elapsed_ms(),
            _truncate_for_log(name),
            count,
            target_rating,
            current_user["id"],
        )
        raise
    finally:
        if db is not None:
            db.close()


@app.delete("/api/sets/{set_id}")
async def delete_set(set_id: int, current_user=Depends(auth_module.require_current_user)):
    db = get_db()
    try:
        deleted = db.execute(
            """
            DELETE FROM puzzle_sets
            WHERE id = %s AND user_id = %s
            RETURNING id
            """,
            (set_id, current_user["id"]),
        ).fetchone()
        if not deleted:
            raise HTTPException(404, "Set not found")
        db.commit()
    finally:
        db.close()
    return {"ok": True}


@app.post("/api/sets/{set_id}/reset")
async def reset_set(set_id: int, current_user=Depends(auth_module.require_current_user)):
    db = get_db()
    try:
        _load_owned_set(db, set_id, current_user["id"])
        db.execute("DELETE FROM cycles WHERE set_id = %s", (set_id,))
        db.commit()
    finally:
        db.close()
    return {"ok": True}


@app.post("/api/sets/{set_id}/cycles")
async def start_cycle(set_id: int, current_user=Depends(auth_module.require_current_user)):
    db = get_db()
    try:
        _load_owned_set(db, set_id, current_user["id"])
        last_cycle = db.execute(
            "SELECT MAX(cycle_number) AS n FROM cycles WHERE set_id = %s",
            (set_id,),
        ).fetchone()
        next_num = (last_cycle["n"] or 0) + 1
        if next_num > WOODPECKER_CYCLE_COUNT:
            raise HTTPException(400, "All scheduled Woodpecker cycles are already complete")

        cycle_id = db.execute(
            """
            INSERT INTO cycles (set_id, cycle_number)
            VALUES (%s, %s)
            RETURNING id
            """,
            (set_id, next_num),
        ).fetchone()["id"]
        db.commit()
    finally:
        db.close()
    return {"id": cycle_id, "cycle_number": next_num}


@app.get("/api/cycles/{cycle_id}")
async def get_cycle(cycle_id: int, current_user=Depends(auth_module.require_current_user)):
    db = get_db()
    try:
        cycle = _load_owned_cycle(db, cycle_id, current_user["id"])
        cycle = _utc_dict(cycle)
        items = db.execute(
            "SELECT * FROM puzzle_set_items WHERE set_id = %s ORDER BY position",
            (cycle["set_id"],),
        ).fetchall()
        completions = db.execute(
            "SELECT puzzle_id, completed_at, solved FROM puzzle_completions WHERE cycle_id = %s",
            (cycle_id,),
        ).fetchall()
        previous_completions = db.execute(
            """
            SELECT pc.puzzle_id, pc.solved
            FROM puzzle_completions pc
            JOIN cycles c ON c.id = pc.cycle_id
            WHERE c.set_id = %s
              AND c.cycle_number = %s
            """,
            (cycle["set_id"], cycle["cycle_number"] - 1),
        ).fetchall()
    finally:
        db.close()

    completions_by_puzzle = {completion["puzzle_id"]: completion for completion in completions}
    previous_solved_by_puzzle = {
        completion["puzzle_id"]: completion["solved"] for completion in previous_completions
    }
    puzzles = []
    for item in items:
        puzzle = dict(item)
        completion = completions_by_puzzle.get(item["puzzle_id"])
        completed_at = completion["completed_at"] if completion else None
        puzzle["completed"] = completed_at is not None
        puzzle["completed_at"] = completed_at
        puzzle["solved"] = completion["solved"] if completion else None
        puzzle["previous_solved"] = previous_solved_by_puzzle.get(item["puzzle_id"])
        puzzles.append(puzzle)
    return {"cycle": cycle, "puzzles": puzzles}


@app.post("/api/cycles/{cycle_id}/replace/{puzzle_id}")
async def replace_puzzle(
    cycle_id: int,
    puzzle_id: str,
    current_user=Depends(auth_module.require_current_user),
):
    db = None

    try:
        db = get_db()
        cycle = _load_owned_cycle(db, cycle_id, current_user["id"])
        if cycle["completed_at"] is not None:
            raise HTTPException(400, "Cycle already finished")

        set_id = cycle["set_id"]
        puzzle_set = db.execute(
            "SELECT target_rating FROM puzzle_sets WHERE id = %s",
            (set_id,),
        ).fetchone()
        item = db.execute(
            """
            SELECT id, set_id, puzzle_id, rating, position
            FROM puzzle_set_items
            WHERE set_id = %s AND puzzle_id = %s
            FOR UPDATE
            """,
            (set_id, puzzle_id),
        ).fetchone()
        if not item:
            raise HTTPException(404, "Puzzle not found in cycle set")

        existing_puzzle_ids = {
            row["puzzle_id"]
            for row in db.execute(
                "SELECT puzzle_id FROM puzzle_set_items WHERE set_id = %s",
                (set_id,),
            ).fetchall()
        }

        try:
            catalog = _get_puzzle_catalog()
        except CatalogNotBuiltError as exc:
            raise HTTPException(503, str(exc)) from exc

        replacement_rating = puzzle_set["target_rating"] if puzzle_set else None
        if replacement_rating is None:
            replacement_rating = item["rating"]
        replacement = catalog.sample_replacement(replacement_rating, existing_puzzle_ids)
        if replacement is None:
            raise HTTPException(409, "No replacement puzzle available")

        db.execute(
            "DELETE FROM puzzle_completions WHERE set_id = %s AND puzzle_id = %s",
            (set_id, puzzle_id),
        )
        db.execute("DELETE FROM puzzle_set_items WHERE id = %s", (item["id"],))
        try:
            new_item = db.execute(
                """
                INSERT INTO puzzle_set_items (set_id, puzzle_id, rating, position)
                VALUES (%s, %s, %s, %s)
                RETURNING id, set_id, puzzle_id, rating, position
                """,
                (
                    set_id,
                    replacement["puzzle_id"],
                    int(replacement["rating"]),
                    item["position"],
                ),
            ).fetchone()
        except errors.UniqueViolation as exc:
            raise HTTPException(409, "Replacement puzzle is already in set") from exc

        _refresh_finished_cycle_counts(db, set_id)
        db.commit()

        puzzle = dict(new_item)
        puzzle["completed"] = False
        puzzle["completed_at"] = None
        puzzle["solved"] = None
        puzzle["previous_solved"] = None
        return puzzle
    finally:
        if db is not None:
            db.close()


@app.post("/api/cycles/{cycle_id}/complete/{puzzle_id}")
async def complete_puzzle(
    cycle_id: int,
    puzzle_id: str,
    completion: CompletePuzzleRequest,
    current_user=Depends(auth_module.require_current_user),
):
    request_started_at = time.perf_counter()
    phase = "request start"
    db = None
    set_id = None

    def elapsed_ms() -> float:
        return (time.perf_counter() - request_started_at) * 1000

    logger.info(
        "complete_puzzle started cycle_id=%s puzzle_id=%s user_id=%s",
        cycle_id,
        _truncate_for_log(puzzle_id),
        current_user["id"],
    )

    try:
        phase = "database connection"
        db = get_db()

        phase = "cycle lookup"
        cycle = _load_owned_cycle(db, cycle_id, current_user["id"])
        if cycle["completed_at"] is not None:
            raise HTTPException(400, "Cycle already finished")
        set_id = cycle["set_id"]

        phase = "completion insert"
        try:
            db.execute(
                """
                INSERT INTO puzzle_completions (cycle_id, set_id, puzzle_id, completed_at, solved)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (cycle_id, puzzle_id) DO UPDATE
                SET solved = EXCLUDED.solved
                """,
                (cycle_id, set_id, puzzle_id, time.time(), completion.solved),
            )
        except errors.ForeignKeyViolation as exc:
            raise HTTPException(404, "Puzzle not found in cycle set") from exc

        phase = "commit"
        db.commit()

        logger.info(
            "complete_puzzle completed cycle_id=%s set_id=%s puzzle_id=%s user_id=%s total=%.1fms",
            cycle_id,
            set_id,
            _truncate_for_log(puzzle_id),
            current_user["id"],
            elapsed_ms(),
        )
        return {"ok": True}
    finally:
        if db is not None:
            db.close()


@app.delete("/api/cycles/{cycle_id}/complete/{puzzle_id}")
async def uncomplete_puzzle(
    cycle_id: int,
    puzzle_id: str,
    current_user=Depends(auth_module.require_current_user),
):
    request_started_at = time.perf_counter()
    phase = "request start"
    db = None
    set_id = None

    def elapsed_ms() -> float:
        return (time.perf_counter() - request_started_at) * 1000

    logger.info(
        "uncomplete_puzzle started cycle_id=%s puzzle_id=%s user_id=%s",
        cycle_id,
        _truncate_for_log(puzzle_id),
        current_user["id"],
    )

    try:
        phase = "database connection"
        db = get_db()

        phase = "cycle lookup"
        cycle = _load_owned_cycle(db, cycle_id, current_user["id"])
        if cycle["completed_at"] is not None:
            raise HTTPException(400, "Cycle already finished")
        set_id = cycle["set_id"]

        phase = "completion delete"
        db.execute(
            "DELETE FROM puzzle_completions WHERE cycle_id = %s AND puzzle_id = %s",
            (cycle_id, puzzle_id),
        )

        phase = "commit"
        db.commit()

        logger.info(
            "uncomplete_puzzle completed cycle_id=%s set_id=%s puzzle_id=%s user_id=%s total=%.1fms",
            cycle_id,
            set_id,
            _truncate_for_log(puzzle_id),
            current_user["id"],
            elapsed_ms(),
        )
        return {"ok": True}
    finally:
        if db is not None:
            db.close()


@app.patch("/api/cycles/{cycle_id}/finish")
async def finish_cycle(cycle_id: int, current_user=Depends(auth_module.require_current_user)):
    db = get_db()
    try:
        _load_owned_cycle(db, cycle_id, current_user["id"])
        completion_counts = db.execute(
            """
            SELECT
                COUNT(*) AS completed_count,
                COUNT(*) FILTER (WHERE solved) AS solved_count
            FROM puzzle_completions
            WHERE cycle_id = %s
            """,
            (cycle_id,),
        ).fetchone()
        completed_count = completion_counts["completed_count"]
        solved_count = completion_counts["solved_count"]
        db.execute(
            """
            UPDATE cycles
            SET completed_at = CURRENT_TIMESTAMP,
                completed_count = %s,
                solved_count = %s
            WHERE id = %s
            """,
            (completed_count, solved_count, cycle_id),
        )
        db.commit()
    finally:
        db.close()
    return {"ok": True, "completed_count": completed_count, "solved_count": solved_count}


@app.get("/api/sets/{set_id}/history")
async def set_history(set_id: int, current_user=Depends(auth_module.require_current_user)):
    db = get_db()
    try:
        _load_owned_set(db, set_id, current_user["id"])
        cycles = db.execute(
            "SELECT * FROM cycles WHERE set_id = %s ORDER BY cycle_number",
            (set_id,),
        ).fetchall()
        total_puzzles = db.execute(
            "SELECT COUNT(*) AS n FROM puzzle_set_items WHERE set_id = %s",
            (set_id,),
        ).fetchone()["n"]
    finally:
        db.close()

    result = []
    for cycle in cycles:
        cycle_dict = dict(cycle)
        started_at = cycle_dict.get("started_at")
        completed_at = cycle_dict.get("completed_at")
        if started_at and completed_at:
            start = _as_utc_datetime(started_at)
            end = _as_utc_datetime(completed_at)
            cycle_dict["duration_days"] = (end.date() - start.date()).days + 1
        else:
            cycle_dict["duration_days"] = None
        for key in TIMESTAMP_FIELDS:
            value = cycle_dict.get(key)
            if value is not None:
                cycle_dict[key] = _as_utc_datetime(value).isoformat().replace(
                    "+00:00",
                    "Z",
                )
        result.append(cycle_dict)

    return {"cycles": result, "total_puzzles": total_puzzles}


@app.get("/{full_path:path}")
async def serve_spa(full_path: str, request: Request):
    if FRONTEND_DEV_URL:
        target_path = f"/{full_path}" if full_path else "/"
        query = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(f"{FRONTEND_DEV_URL}{target_path}{query}")

    if full_path:
        static_file = _resolve_frontend_file(full_path)
        if static_file:
            return FileResponse(static_file)

    index_path = os.path.join(FRONTEND_DIST, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"detail": "Frontend not built. Run 'npm run build' in frontend/."}


if __name__ == "__main__":
    import uvicorn

    reload_enabled = os.environ.get("UVICORN_RELOAD") == "1"
    uvicorn.run(
        "main:app" if reload_enabled else app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=reload_enabled,
    )
