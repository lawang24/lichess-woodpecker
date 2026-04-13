import os
import time
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

try:
    from .database import close_db, get_db, init_db
    from .puzzle_catalog import CatalogNotBuiltError, PuzzleCatalog
except ImportError:
    from database import close_db, get_db, init_db
    from puzzle_catalog import CatalogNotBuiltError, PuzzleCatalog

BACKEND_DIR = os.path.abspath(os.path.dirname(__file__))
FRONTEND_DIST = os.path.join(BACKEND_DIR, "static")
FRONTEND_DEV_URL = os.environ.get("FRONTEND_DEV_URL", "").rstrip("/")
TIMESTAMP_FIELDS = {"created_at", "started_at", "completed_at"}
logger = logging.getLogger("uvicorn.error")


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


def _truncate_for_log(value: str, limit: int = 80) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


@asynccontextmanager
async def lifespan(app: FastAPI):
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


@app.get("/api/sets")
async def list_sets():
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
async def get_set(set_id: int):
    db = get_db()
    try:
        puzzle_set = db.execute(
            "SELECT * FROM puzzle_sets WHERE id = %s",
            (set_id,),
        ).fetchone()
        if not puzzle_set:
            raise HTTPException(404, "Set not found")
        items = db.execute(
            "SELECT * FROM puzzle_set_items WHERE set_id = %s ORDER BY position",
            (set_id,),
        ).fetchall()
    finally:
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
            "create_set started name=%r count=%s rating=%s",
            _truncate_for_log(name),
            count,
            target_rating,
        )
        logger.info("create_set parsed request in %.1fms", elapsed_ms())

        phase = "puzzle catalog load"
        try:
            catalog = _get_puzzle_catalog()
        except CatalogNotBuiltError as exc:
            logger.error(
                "create_set failed during %s after %.1fms name=%r count=%s rating=%s: %s",
                phase,
                elapsed_ms(),
                _truncate_for_log(name),
                count,
                target_rating,
                exc,
            )
            raise HTTPException(503, str(exc)) from exc
        logger.info("create_set loaded puzzle catalog in %.1fms", elapsed_ms())

        phase = "puzzle sampling"
        if target_rating is not None:
            sample = catalog.sample_by_rating(count, target_rating)
        else:
            sample = catalog.sample_random(count)
        logger.info(
            "create_set sampled puzzles in %.1fms requested=%s actual=%s",
            elapsed_ms(),
            count,
            len(sample),
        )

        phase = "database connection"
        db = get_db()
        logger.info("create_set acquired database connection in %.1fms", elapsed_ms())

        phase = "set insert"
        set_id = db.execute(
            "INSERT INTO puzzle_sets (name, target_rating) VALUES (%s, %s) RETURNING id",
            (name, target_rating),
        ).fetchone()["id"]
        logger.info("create_set inserted puzzle set id=%s in %.1fms", set_id, elapsed_ms())

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
        logger.info(
            "create_set bulk inserted %s puzzle_set_items in %.1fms",
            len(sample),
            elapsed_ms(),
        )

        phase = "commit"
        db.commit()
        logger.info("create_set committed transaction in %.1fms", elapsed_ms())

        logger.info(
            "create_set completed id=%s name=%r requested=%s actual=%s total=%.1fms",
            set_id,
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
            "create_set failed during %s after %.1fms name=%r count=%s rating=%s",
            phase,
            elapsed_ms(),
            _truncate_for_log(name),
            count,
            target_rating,
        )
        raise
    finally:
        if db is not None:
            db.close()


@app.delete("/api/sets/{set_id}")
async def delete_set(set_id: int):
    db = get_db()
    try:
        db.execute("DELETE FROM puzzle_sets WHERE id = %s", (set_id,))
        db.commit()
    finally:
        db.close()
    return {"ok": True}


@app.post("/api/sets/{set_id}/reset")
async def reset_set(set_id: int):
    db = get_db()
    try:
        db.execute("DELETE FROM cycles WHERE set_id = %s", (set_id,))
        db.commit()
    finally:
        db.close()
    return {"ok": True}


@app.post("/api/sets/{set_id}/cycles")
async def start_cycle(set_id: int):
    db = get_db()
    try:
        puzzle_set = db.execute(
            "SELECT * FROM puzzle_sets WHERE id = %s",
            (set_id,),
        ).fetchone()
        if not puzzle_set:
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
    finally:
        db.close()
    return {"id": cycle_id, "cycle_number": next_num}


@app.get("/api/cycles/{cycle_id}")
async def get_cycle(cycle_id: int):
    db = get_db()
    try:
        cycle = db.execute(
            "SELECT * FROM cycles WHERE id = %s",
            (cycle_id,),
        ).fetchone()
        if not cycle:
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
    finally:
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
    request_started_at = time.perf_counter()
    phase = "request start"
    db = None
    set_id = None

    def elapsed_ms() -> float:
        return (time.perf_counter() - request_started_at) * 1000

    logger.info(
        "complete_puzzle started cycle_id=%s puzzle_id=%s",
        cycle_id,
        _truncate_for_log(puzzle_id),
    )

    try:
        phase = "database connection"
        db = get_db()
        logger.info(
            "complete_puzzle acquired database connection in %.1fms cycle_id=%s puzzle_id=%s",
            elapsed_ms(),
            cycle_id,
            _truncate_for_log(puzzle_id),
        )

        phase = "cycle lookup"
        cycle = db.execute(
            "SELECT * FROM cycles WHERE id = %s",
            (cycle_id,),
        ).fetchone()
        logger.info(
            "complete_puzzle loaded cycle in %.1fms cycle_id=%s found=%s",
            elapsed_ms(),
            cycle_id,
            bool(cycle),
        )
        if not cycle:
            raise HTTPException(404, "Cycle not found")

        phase = "cycle validation"
        if cycle["completed_at"] is not None:
            raise HTTPException(400, "Cycle already finished")
        set_id = cycle["set_id"]
        logger.info(
            "complete_puzzle validated cycle state in %.1fms cycle_id=%s set_id=%s",
            elapsed_ms(),
            cycle_id,
            set_id,
        )

        phase = "set membership lookup"
        item = db.execute(
            "SELECT 1 FROM puzzle_set_items WHERE set_id = %s AND puzzle_id = %s",
            (set_id, puzzle_id),
        ).fetchone()
        logger.info(
            "complete_puzzle verified puzzle membership in %.1fms cycle_id=%s set_id=%s puzzle_id=%s found=%s",
            elapsed_ms(),
            cycle_id,
            set_id,
            _truncate_for_log(puzzle_id),
            bool(item),
        )
        if not item:
            raise HTTPException(404, "Puzzle not in this set")

        phase = "total puzzle count"
        total = db.execute(
            "SELECT COUNT(*) AS n FROM puzzle_set_items WHERE set_id = %s",
            (set_id,),
        ).fetchone()["n"]
        logger.info(
            "complete_puzzle counted total puzzles in %.1fms cycle_id=%s set_id=%s total=%s",
            elapsed_ms(),
            cycle_id,
            set_id,
            total,
        )

        phase = "completion insert"
        db.execute(
            """
            INSERT INTO cycle_completions (cycle_id, puzzle_id, completed_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (cycle_id, puzzle_id) DO NOTHING
            """,
            (cycle_id, puzzle_id, time.time()),
        )
        logger.info(
            "complete_puzzle inserted completion in %.1fms cycle_id=%s puzzle_id=%s",
            elapsed_ms(),
            cycle_id,
            _truncate_for_log(puzzle_id),
        )

        phase = "commit"
        db.commit()
        logger.info(
            "complete_puzzle committed transaction in %.1fms cycle_id=%s puzzle_id=%s",
            elapsed_ms(),
            cycle_id,
            _truncate_for_log(puzzle_id),
        )

        phase = "completed count lookup"
        done_count = db.execute(
            "SELECT COUNT(*) AS n FROM cycle_completions WHERE cycle_id = %s",
            (cycle_id,),
        ).fetchone()["n"]
        logger.info(
            "complete_puzzle counted completed puzzles in %.1fms cycle_id=%s done=%s total=%s",
            elapsed_ms(),
            cycle_id,
            done_count,
            total,
        )

        all_done = done_count >= total
        logger.info(
            "complete_puzzle completed cycle_id=%s set_id=%s puzzle_id=%s all_done=%s total=%.1fms",
            cycle_id,
            set_id,
            _truncate_for_log(puzzle_id),
            all_done,
            elapsed_ms(),
        )
        return {"ok": True, "all_done": all_done}
    except HTTPException as exc:
        logger.warning(
            "complete_puzzle rejected during %s after %.1fms cycle_id=%s set_id=%s puzzle_id=%s status=%s detail=%s",
            phase,
            elapsed_ms(),
            cycle_id,
            set_id,
            _truncate_for_log(puzzle_id),
            exc.status_code,
            exc.detail,
        )
        raise
    except Exception:
        logger.exception(
            "complete_puzzle failed during %s after %.1fms cycle_id=%s set_id=%s puzzle_id=%s",
            phase,
            elapsed_ms(),
            cycle_id,
            set_id,
            _truncate_for_log(puzzle_id),
        )
        raise
    finally:
        if db is not None:
            db.close()


@app.delete("/api/cycles/{cycle_id}/complete/{puzzle_id}")
async def uncomplete_puzzle(cycle_id: int, puzzle_id: str):
    request_started_at = time.perf_counter()
    phase = "request start"
    db = None
    set_id = None

    def elapsed_ms() -> float:
        return (time.perf_counter() - request_started_at) * 1000

    logger.info(
        "uncomplete_puzzle started cycle_id=%s puzzle_id=%s",
        cycle_id,
        _truncate_for_log(puzzle_id),
    )

    try:
        phase = "database connection"
        db = get_db()
        logger.info(
            "uncomplete_puzzle acquired database connection in %.1fms cycle_id=%s puzzle_id=%s",
            elapsed_ms(),
            cycle_id,
            _truncate_for_log(puzzle_id),
        )

        phase = "cycle lookup"
        cycle = db.execute(
            "SELECT * FROM cycles WHERE id = %s",
            (cycle_id,),
        ).fetchone()
        logger.info(
            "uncomplete_puzzle loaded cycle in %.1fms cycle_id=%s found=%s",
            elapsed_ms(),
            cycle_id,
            bool(cycle),
        )
        if not cycle:
            raise HTTPException(404, "Cycle not found")

        phase = "cycle validation"
        if cycle["completed_at"] is not None:
            raise HTTPException(400, "Cycle already finished")
        set_id = cycle["set_id"]
        logger.info(
            "uncomplete_puzzle validated cycle state in %.1fms cycle_id=%s set_id=%s",
            elapsed_ms(),
            cycle_id,
            set_id,
        )

        phase = "completion delete"
        db.execute(
            "DELETE FROM cycle_completions WHERE cycle_id = %s AND puzzle_id = %s",
            (cycle_id, puzzle_id),
        )
        logger.info(
            "uncomplete_puzzle deleted completion in %.1fms cycle_id=%s puzzle_id=%s",
            elapsed_ms(),
            cycle_id,
            _truncate_for_log(puzzle_id),
        )

        phase = "commit"
        db.commit()
        logger.info(
            "uncomplete_puzzle committed transaction in %.1fms cycle_id=%s puzzle_id=%s",
            elapsed_ms(),
            cycle_id,
            _truncate_for_log(puzzle_id),
        )

        logger.info(
            "uncomplete_puzzle completed cycle_id=%s set_id=%s puzzle_id=%s total=%.1fms",
            cycle_id,
            set_id,
            _truncate_for_log(puzzle_id),
            elapsed_ms(),
        )
        return {"ok": True}
    except HTTPException as exc:
        logger.warning(
            "uncomplete_puzzle rejected during %s after %.1fms cycle_id=%s set_id=%s puzzle_id=%s status=%s detail=%s",
            phase,
            elapsed_ms(),
            cycle_id,
            set_id,
            _truncate_for_log(puzzle_id),
            exc.status_code,
            exc.detail,
        )
        raise
    except Exception:
        logger.exception(
            "uncomplete_puzzle failed during %s after %.1fms cycle_id=%s set_id=%s puzzle_id=%s",
            phase,
            elapsed_ms(),
            cycle_id,
            set_id,
            _truncate_for_log(puzzle_id),
        )
        raise
    finally:
        if db is not None:
            db.close()


@app.patch("/api/cycles/{cycle_id}/finish")
async def finish_cycle(cycle_id: int):
    db = get_db()
    try:
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
    finally:
        db.close()
    return {"ok": True, "completed_count": completed_count}


@app.get("/api/sets/{set_id}/history")
async def set_history(set_id: int):
    db = get_db()
    try:
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
