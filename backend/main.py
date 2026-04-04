import os
import time
from contextlib import asynccontextmanager
from datetime import datetime

import pandas as pd
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from database import get_db, init_db

ROOT_DIR = os.path.join(os.path.dirname(__file__), "..")

TIMESTAMP_FIELDS = {"created_at", "started_at", "completed_at"}


def _utc_dict(row) -> dict:
    """Convert a sqlite3.Row to a dict, appending 'Z' to timestamp fields so JS treats them as UTC."""
    d = dict(row)
    for k in TIMESTAMP_FIELDS:
        if k in d and d[k] is not None and not d[k].endswith("Z"):
            d[k] = d[k] + "Z"
    return d
PUZZLE_CSV = os.path.join(ROOT_DIR, "data", "puzzles.csv.zst")
FRONTEND_DIST = os.path.join(ROOT_DIR, "frontend", "dist")




@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    app.state.puzzle_df = pd.read_csv(
        PUZZLE_CSV, usecols=["PuzzleId", "Rating"]
    )
    yield


app = FastAPI(lifespan=lifespan)

# Serve React build if it exists (production mode)
if os.path.isdir(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")


# --- Puzzle Sets ---

@app.get("/api/sets")
async def list_sets():
    db = get_db()
    sets = db.execute("""
        SELECT s.*, COUNT(i.id) as puzzle_count
        FROM puzzle_sets s
        LEFT JOIN puzzle_set_items i ON i.set_id = s.id
        GROUP BY s.id
        ORDER BY s.created_at DESC
    """).fetchall()
    cycles = db.execute("""
        SELECT id, set_id, cycle_number, started_at, completed_at
        FROM cycles ORDER BY cycle_number
    """).fetchall()
    db.close()
    cycles_by_set = {}
    for c in cycles:
        cd = _utc_dict(c)
        cycles_by_set.setdefault(cd["set_id"], []).append(cd)
    result = []
    for s in sets:
        d = _utc_dict(s)
        d["cycles"] = cycles_by_set.get(d["id"], [])
        result.append(d)
    return result


@app.get("/api/sets/{set_id}")
async def get_set(set_id: int):
    db = get_db()
    puzzle_set = db.execute("SELECT * FROM puzzle_sets WHERE id = ?", (set_id,)).fetchone()
    if not puzzle_set:
        db.close()
        raise HTTPException(404, "Set not found")
    items = db.execute(
        "SELECT * FROM puzzle_set_items WHERE set_id = ? ORDER BY position", (set_id,)
    ).fetchall()
    db.close()
    return {"set": _utc_dict(puzzle_set), "puzzles": [dict(i) for i in items]}


RATING_BANDS = [
    # (weight, low_offset, high_offset)
    (0.50, -150, 150),    # 50% — target ± 150
    (0.30, -400, -150),   # 30% — below by 150–400
    (0.15, 150, 300),     # 15% — above by 150–300
    (0.05, 300, None),    # 5%  — above by 300+
]


def _sample_by_rating(df: pd.DataFrame, count: int, rating: int) -> pd.DataFrame:
    parts = []
    for weight, lo, hi in RATING_BANDS:
        n = round(count * weight)
        low = rating + lo
        band = df[df["Rating"] >= low]
        if hi is not None:
            band = band[band["Rating"] <= rating + hi]
        parts.append(band.sample(n=min(n, len(band))))
    return pd.concat(parts).drop_duplicates(subset="PuzzleId")


@app.post("/api/sets")
async def create_set(request: Request):
    body = await request.json()
    name = body.get("name", "Untitled Set")
    count = body.get("count", 50)
    rating = body.get("rating")

    df = request.app.state.puzzle_df
    if rating:
        sample = _sample_by_rating(df, count, int(rating))
    else:
        sample = df.sample(n=min(count, len(df)))

    db = get_db()
    cursor = db.execute(
        "INSERT INTO puzzle_sets (name, target_rating) VALUES (?, ?)", (name, rating)
    )
    set_id = cursor.lastrowid
    for i, (_, row) in enumerate(sample.iterrows()):
        db.execute(
            "INSERT INTO puzzle_set_items (set_id, puzzle_id, rating, position) VALUES (?, ?, ?, ?)",
            (set_id, row["PuzzleId"], int(row["Rating"]), i),
        )
    db.commit()
    db.close()
    return {"id": set_id, "name": name, "count": len(sample)}


@app.delete("/api/sets/{set_id}")
async def delete_set(set_id: int):
    db = get_db()
    db.execute("DELETE FROM puzzle_sets WHERE id = ?", (set_id,))
    db.commit()
    db.close()
    return {"ok": True}


@app.post("/api/sets/{set_id}/reset")
async def reset_set(set_id: int):
    db = get_db()
    db.execute("DELETE FROM cycles WHERE set_id = ?", (set_id,))
    db.commit()
    db.close()
    return {"ok": True}


# --- Cycles ---

@app.post("/api/sets/{set_id}/cycles")
async def start_cycle(set_id: int):
    db = get_db()
    puzzle_set = db.execute("SELECT * FROM puzzle_sets WHERE id = ?", (set_id,)).fetchone()
    if not puzzle_set:
        db.close()
        raise HTTPException(404, "Set not found")
    # Get next cycle number
    last = db.execute(
        "SELECT MAX(cycle_number) as n FROM cycles WHERE set_id = ?", (set_id,)
    ).fetchone()
    next_num = (last["n"] or 0) + 1
    cursor = db.execute(
        "INSERT INTO cycles (set_id, cycle_number) VALUES (?, ?)",
        (set_id, next_num),
    )
    cycle_id = cursor.lastrowid
    db.commit()
    db.close()
    return {"id": cycle_id, "cycle_number": next_num}


@app.get("/api/cycles/{cycle_id}")
async def get_cycle(cycle_id: int):
    db = get_db()
    cycle = db.execute("SELECT * FROM cycles WHERE id = ?", (cycle_id,)).fetchone()
    if not cycle:
        db.close()
        raise HTTPException(404, "Cycle not found")
    cycle = _utc_dict(cycle)
    items = db.execute(
        "SELECT * FROM puzzle_set_items WHERE set_id = ? ORDER BY position",
        (cycle["set_id"],),
    ).fetchall()
    completions = db.execute(
        "SELECT puzzle_id, completed_at FROM cycle_completions WHERE cycle_id = ?",
        (cycle_id,),
    ).fetchall()
    db.close()
    completed_map = {r["puzzle_id"]: r["completed_at"] for r in completions}
    puzzles = []
    for item in items:
        d = dict(item)
        ts = completed_map.get(item["puzzle_id"])
        d["completed"] = ts is not None
        d["completed_at"] = ts
        puzzles.append(d)
    return {"cycle": cycle, "puzzles": puzzles}


@app.post("/api/cycles/{cycle_id}/complete/{puzzle_id}")
async def complete_puzzle(cycle_id: int, puzzle_id: str):
    db = get_db()
    cycle = db.execute("SELECT * FROM cycles WHERE id = ?", (cycle_id,)).fetchone()
    if not cycle:
        db.close()
        raise HTTPException(404, "Cycle not found")
    if cycle["completed_at"] is not None:
        db.close()
        raise HTTPException(400, "Cycle already finished")
    item = db.execute(
        "SELECT 1 FROM puzzle_set_items WHERE set_id = ? AND puzzle_id = ?",
        (cycle["set_id"], puzzle_id),
    ).fetchone()
    if not item:
        db.close()
        raise HTTPException(404, "Puzzle not in this set")
    total = db.execute(
        "SELECT COUNT(*) as n FROM puzzle_set_items WHERE set_id = ?",
        (cycle["set_id"],),
    ).fetchone()["n"]

    db.execute(
        "INSERT OR IGNORE INTO cycle_completions (cycle_id, puzzle_id, completed_at) VALUES (?, ?, ?)",
        (cycle_id, puzzle_id, time.time()),
    )
    db.commit()
    done_count = db.execute(
        "SELECT COUNT(*) as n FROM cycle_completions WHERE cycle_id = ?",
        (cycle_id,),
    ).fetchone()["n"]
    db.close()

    return {"ok": True, "all_done": done_count >= total}


@app.delete("/api/cycles/{cycle_id}/complete/{puzzle_id}")
async def uncomplete_puzzle(cycle_id: int, puzzle_id: str):
    db = get_db()
    cycle = db.execute("SELECT * FROM cycles WHERE id = ?", (cycle_id,)).fetchone()
    if not cycle:
        db.close()
        raise HTTPException(404, "Cycle not found")
    if cycle["completed_at"] is not None:
        db.close()
        raise HTTPException(400, "Cycle already finished")
    db.execute(
        "DELETE FROM cycle_completions WHERE cycle_id = ? AND puzzle_id = ?",
        (cycle_id, puzzle_id),
    )
    db.commit()
    db.close()
    return {"ok": True}


@app.patch("/api/cycles/{cycle_id}/finish")
async def finish_cycle(cycle_id: int):
    db = get_db()
    completed_count = db.execute(
        "SELECT COUNT(*) as n FROM cycle_completions WHERE cycle_id = ?",
        (cycle_id,),
    ).fetchone()["n"]
    db.execute(
        """UPDATE cycles
           SET completed_at = CURRENT_TIMESTAMP,
               completed_count = ?
           WHERE id = ?""",
        (completed_count, cycle_id),
    )
    db.commit()
    db.close()
    return {"ok": True, "completed_count": completed_count}


# --- Dashboard ---

@app.get("/api/sets/{set_id}/history")
async def set_history(set_id: int):
    db = get_db()
    cycles = db.execute(
        "SELECT * FROM cycles WHERE set_id = ? ORDER BY cycle_number",
        (set_id,),
    ).fetchall()
    total_puzzles = db.execute(
        "SELECT COUNT(*) as n FROM puzzle_set_items WHERE set_id = ?", (set_id,)
    ).fetchone()["n"]
    db.close()

    result = []
    for c in cycles:
        d = dict(c)
        if d["started_at"] and d["completed_at"]:
            start = datetime.fromisoformat(d["started_at"])
            end = datetime.fromisoformat(d["completed_at"])
            d["duration_days"] = (end.date() - start.date()).days + 1
        else:
            d["duration_days"] = None
        for k in TIMESTAMP_FIELDS:
            if k in d and d[k] is not None and not d[k].endswith("Z"):
                d[k] = d[k] + "Z"
        result.append(d)

    return {"cycles": result, "total_puzzles": total_puzzles}


# --- Chess.com ratings ---

@app.get("/api/ratings")
async def get_chess_com_ratings(start_date: str = None, end_date: str = None):
    from chess_com import backfill_ratings, get_ratings
    await backfill_ratings("lagoat420", start_date, end_date)
    ratings = get_ratings("lagoat420", start_date, end_date)
    return {"ratings": ratings}


# --- SPA catch-all (serves React index.html for client-side routing) ---

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    index_path = os.path.join(FRONTEND_DIST, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"detail": "Frontend not built. Run 'npm run build' in frontend/."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
