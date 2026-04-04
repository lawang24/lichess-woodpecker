import httpx
from datetime import datetime, timedelta, timezone
from database import get_db

CHESS_COM_BASE = "https://api.chess.com/pub"


async def backfill_ratings(username: str, start_date: str, end_date: str) -> dict:
    # Include the prior month so we have a seed rating for forward-fill
    prev_month_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(day=1) - timedelta(days=1)
    start_month = prev_month_dt.strftime("%Y/%m")
    end_month = end_date[:7].replace("-", "/")

    db = get_db()
    row = db.execute(
        "SELECT MAX(date) FROM chess_com_ratings WHERE username = ? AND date BETWEEN ? AND ?",
        (username, start_date, end_date),
    ).fetchone()
    last_date = row[0] if row else None
    last_month = last_date[:7].replace("-", "/") if last_date else None

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{CHESS_COM_BASE}/player/{username}/games/archives")
        resp.raise_for_status()
        archives = resp.json()["archives"]

        # Only fetch months within the requested window
        archives = [url for url in archives if start_month <= url[-7:] <= end_month]

        # Skip months we already have, except re-fetch from last stored month onward
        if last_month:
            archives = [url for url in archives if url[-7:] >= last_month]

        months_fetched = 0
        ratings_upserted = 0

        for archive_url in archives:
            resp = await client.get(archive_url)
            resp.raise_for_status()
            games = resp.json().get("games", [])

            daily_ratings = {}
            for game in games:
                end_time = game.get("end_time")
                time_class = game.get("time_class")
                if not end_time or time_class != "rapid":
                    continue

                white = game.get("white", {})
                black = game.get("black", {})
                if white.get("username", "").lower() == username.lower():
                    rating = white.get("rating")
                elif black.get("username", "").lower() == username.lower():
                    rating = black.get("rating")
                else:
                    continue

                if not rating:
                    continue

                date_str = datetime.fromtimestamp(end_time, tz=timezone.utc).strftime("%Y-%m-%d")
                if date_str < start_date or date_str > end_date:
                    continue

                if date_str not in daily_ratings or end_time > daily_ratings[date_str][1]:
                    daily_ratings[date_str] = (rating, end_time)

            for date_str, (rating, _) in daily_ratings.items():
                db.execute(
                    "INSERT OR REPLACE INTO chess_com_ratings (username, date, time_class, rating) VALUES (?, ?, ?, ?)",
                    (username, date_str, "rapid", rating),
                )
                ratings_upserted += 1

            months_fetched += 1

        db.commit()
        db.close()

    return {"months_fetched": months_fetched, "ratings_upserted": ratings_upserted}


def get_ratings(username: str, start_date: str, end_date: str) -> list:
    db = get_db()

    # Get the most recent rating before the window to seed forward-fill
    seed = db.execute(
        "SELECT rating FROM chess_com_ratings WHERE username = ? AND time_class = 'rapid' AND date <= ? ORDER BY date DESC LIMIT 1",
        (username, start_date),
    ).fetchone()

    rows = db.execute(
        "SELECT date, rating FROM chess_com_ratings WHERE username = ? AND time_class = 'rapid' AND date BETWEEN ? AND ? ORDER BY date",
        (username, start_date, end_date),
    ).fetchall()
    db.close()

    rating_map = {r["date"]: r["rating"] for r in rows}

    # Fill every day, carrying forward the previous rating
    result = []
    current_rating = seed["rating"] if seed else None
    d = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    while d <= end:
        date_str = d.strftime("%Y-%m-%d")
        if date_str in rating_map:
            current_rating = rating_map[date_str]
        if current_rating is not None:
            result.append({"date": date_str, "rating": current_rating})
        d += timedelta(days=1)

    return result
