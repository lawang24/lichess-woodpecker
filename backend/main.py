import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

try:
    from .database import get_db, init_db
    from .puzzle_catalog import CatalogNotBuiltError, PuzzleCatalog
except ImportError:
    from database import get_db, init_db
    from puzzle_catalog import CatalogNotBuiltError, PuzzleCatalog

BACKEND_DIR = os.path.abspath(os.path.dirname(__file__))
FRONTEND_DIST = os.path.join(BACKEND_DIR, "static")
FRONTEND_DEV_URL = os.environ.get("FRONTEND_DEV_URL", "").rstrip("/")
TIMESTAMP_FIELDS = {"created_at", "started_at", "completed_at"}


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
    d = dict(row)
    for key in TIMESTAMP_FIELDS:
        value = d.get(key)
        if value is not None:
            d[key] = _as_utc_datetime(value).isoformat().replace("+00:00", "Z")
    return d


def _resolve_frontend_file(full_path: str) -> str | None:
    candidate = os.path.abspath(os.path.join(FRONTEND_DIST, full_path))
    static_root = os.path.abspath(FRONTEND_DIST)
    if os.path.commonpath([candidate, static_root]) != static_root:
        return None
    if os.path.isfile(candidate):
        return candidate
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)

if not FRONTEND_DEV_URL and os.path.isdir(FRONTEND_DIST):
    app.mount(
        "/assets",
        StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")),
        name="assets",
    )


@app.get("/api/sets")
async def list_sets():
    db = get_db()
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
        GROUP BY s.id, s.name, s.target_rating, s.created_at
        ORDER BY s.created_at DESC
        """
    ).fetchall()
    cycles = db.execute(
        """
        SELECT id, set_id, cycle_number, started_at, completed_at
        FROM cycles
        ORDER BY cycle_number
        """
    ).fetchall()
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
async def get_set(set_id: int):
    db = get_db()
    puzzle_set = db.execute(
        "SELECT * FROM puzzle_sets WHERE id = %s",
        (set_id,),
    ).fetchone()
    if not puzzle_set:
        db.close()
        raise HTTPException(404, "Set not found")
    items = db.execute(
        "SELECT * FROM puzzle_set_items WHERE set_id = %s ORDER BY position",
        (set_id,),
    ).fetchall()
    db.close()
    return {"set": _utc_dict(puzzle_set), "puzzles": [dict(item) for item in items]}


_puzzle_catalog = None


def _get_puzzle_catalog() -> PuzzleCatalog:
    global _puzzle_catalog

    if _puzzle_catalog is None:
        _puzzle_catalog = PuzzleCatalog.load()

    return _puzzle_catalog


@app.post("/api/sets")
async def create_set(request: Request):
    body = await request.json()
    name = body.get("name", "Untitled Set")
    count = int(body.get("count", 50))
    rating = body.get("rating")
    target_rating = int(rating) if rating is not None else None

    try:
        catalog = _get_puzzle_catalog()
    except CatalogNotBuiltError as exc:
        raise HTTPException(503, str(exc)) from exc

    if target_rating is not None:
        sample = catalog.sample_by_rating(count, target_rating)
    else:
        sample = catalog.sample_random(count)

    db = get_db()
    set_id = db.execute(
        "INSERT INTO puzzle_sets (name, target_rating) VALUES (%s, %s) RETURNING id",
        (name, target_rating),
    ).fetchone()["id"]
    for index, row in enumerate(sample):
        db.execute(
            """
            INSERT INTO puzzle_set_items (set_id, puzzle_id, rating, position)
            VALUES (%s, %s, %s, %s)
            """,
            (set_id, row["puzzle_id"], int(row["rating"]), index),
        )
    db.commit()
    db.close()
    return {"id": set_id, "name": name, "count": len(sample)}


@app.delete("/api/sets/{set_id}")
async def delete_set(set_id: int):
    db = get_db()
    db.execute("DELETE FROM puzzle_sets WHERE id = %s", (set_id,))
    db.commit()
    db.close()
    return {"ok": True}


@app.post("/api/sets/{set_id}/reset")
async def reset_set(set_id: int):
    db = get_db()
    db.execute("DELETE FROM cycles WHERE set_id = %s", (set_id,))
    db.commit()
    db.close()
    return {"ok": True}


@app.post("/api/sets/{set_id}/cycles")
async def start_cycle(set_id: int):
    db = get_db()
    puzzle_set = db.execute(
        "SELECT * FROM puzzle_sets WHERE id = %s",
        (set_id,),
    ).fetchone()
    if not puzzle_set:
        db.close()
        raise HTTPException(404, "Set not found")
    last_cycle = db.execute(
        "SELECT MAX(cycle_number) AS n FROM cycles WHERE set_id = %s",
        (set_id,),
    ).fetchone()
    next_num = (last_cycle["n"] or 0) + 1
    cycle_id = db.execute(
        """
        INSERT INTO cycles (set_id, cycle_number)
        VALUES (%s, %s)
        RETURNING id
        """,
        (set_id, next_num),
    ).fetchone()["id"]
    db.commit()
    db.close()
    return {"id": cycle_id, "cycle_number": next_num}


@app.get("/api/cycles/{cycle_id}")
async def get_cycle(cycle_id: int):
    db = get_db()
    cycle = db.execute(
        "SELECT * FROM cycles WHERE id = %s",
        (cycle_id,),
    ).fetchone()
    if not cycle:
        db.close()
        raise HTTPException(404, "Cycle not found")
    cycle = _utc_dict(cycle)
    items = db.execute(
        "SELECT * FROM puzzle_set_items WHERE set_id = %s ORDER BY position",
        (cycle["set_id"],),
    ).fetchall()
    completions = db.execute(
        "SELECT puzzle_id, completed_at FROM cycle_completions WHERE cycle_id = %s",
        (cycle_id,),
    ).fetchall()
    db.close()

    completed_map = {
        completion["puzzle_id"]: completion["completed_at"] for completion in completions
    }
    puzzles = []
    for item in items:
        puzzle = dict(item)
        completed_at = completed_map.get(item["puzzle_id"])
        puzzle["completed"] = completed_at is not None
        puzzle["completed_at"] = completed_at
        puzzles.append(puzzle)
    return {"cycle": cycle, "puzzles": puzzles}


@app.post("/api/cycles/{cycle_id}/complete/{puzzle_id}")
async def complete_puzzle(cycle_id: int, puzzle_id: str):
    db = get_db()
    cycle = db.execute(
        "SELECT * FROM cycles WHERE id = %s",
        (cycle_id,),
    ).fetchone()
    if not cycle:
        db.close()
        raise HTTPException(404, "Cycle not found")
    if cycle["completed_at"] is not None:
        db.close()
        raise HTTPException(400, "Cycle already finished")
    item = db.execute(
        "SELECT 1 FROM puzzle_set_items WHERE set_id = %s AND puzzle_id = %s",
        (cycle["set_id"], puzzle_id),
    ).fetchone()
    if not item:
        db.close()
        raise HTTPException(404, "Puzzle not in this set")
    total = db.execute(
        "SELECT COUNT(*) AS n FROM puzzle_set_items WHERE set_id = %s",
        (cycle["set_id"],),
    ).fetchone()["n"]

    db.execute(
        """
        INSERT INTO cycle_completions (cycle_id, puzzle_id, completed_at)
        VALUES (%s, %s, %s)
        ON CONFLICT (cycle_id, puzzle_id) DO NOTHING
        """,
        (cycle_id, puzzle_id, time.time()),
    )
    db.commit()
    done_count = db.execute(
        "SELECT COUNT(*) AS n FROM cycle_completions WHERE cycle_id = %s",
        (cycle_id,),
    ).fetchone()["n"]
    db.close()

    return {"ok": True, "all_done": done_count >= total}


@app.delete("/api/cycles/{cycle_id}/complete/{puzzle_id}")
async def uncomplete_puzzle(cycle_id: int, puzzle_id: str):
    db = get_db()
    cycle = db.execute(
        "SELECT * FROM cycles WHERE id = %s",
        (cycle_id,),
    ).fetchone()
    if not cycle:
        db.close()
        raise HTTPException(404, "Cycle not found")
    if cycle["completed_at"] is not None:
        db.close()
        raise HTTPException(400, "Cycle already finished")
    db.execute(
        "DELETE FROM cycle_completions WHERE cycle_id = %s AND puzzle_id = %s",
        (cycle_id, puzzle_id),
    )
    db.commit()
    db.close()
    return {"ok": True}


@app.patch("/api/cycles/{cycle_id}/finish")
async def finish_cycle(cycle_id: int):
    db = get_db()
    completed_count = db.execute(
        "SELECT COUNT(*) AS n FROM cycle_completions WHERE cycle_id = %s",
        (cycle_id,),
    ).fetchone()["n"]
    db.execute(
        """
        UPDATE cycles
        SET completed_at = CURRENT_TIMESTAMP,
            completed_count = %s
        WHERE id = %s
        """,
        (completed_count, cycle_id),
    )
    db.commit()
    db.close()
    return {"ok": True, "completed_count": completed_count}


@app.get("/api/sets/{set_id}/history")
async def set_history(set_id: int):
    db = get_db()
    cycles = db.execute(
        "SELECT * FROM cycles WHERE set_id = %s ORDER BY cycle_number",
        (set_id,),
    ).fetchall()
    total_puzzles = db.execute(
        "SELECT COUNT(*) AS n FROM puzzle_set_items WHERE set_id = %s",
        (set_id,),
    ).fetchone()["n"]
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
                    "+00:00", "Z"
                )
        result.append(cycle_dict)

    return {"cycles": result, "total_puzzles": total_puzzles}


@app.get("/api/ratings")
async def get_chess_com_ratings(start_date: str = None, end_date: str = None):
    try:
        from .chess_com import backfill_ratings, get_ratings
    except ImportError:
        from chess_com import backfill_ratings, get_ratings

    await backfill_ratings("lagoat420", start_date, end_date)
    ratings = get_ratings("lagoat420", start_date, end_date)
    return {"ratings": ratings}


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

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=os.environ.get("UVICORN_RELOAD") == "1",
    )
