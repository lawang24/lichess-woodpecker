from datetime import datetime, timedelta, timezone

import httpx

try:
    from .database import get_db
except ImportError:
    from database import get_db

CHESS_COM_BASE = "https://api.chess.com/pub"


async def backfill_ratings(username: str, start_date: str, end_date: str) -> dict:
    prev_month_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(day=1) - timedelta(
        days=1
    )
    start_month = prev_month_dt.strftime("%Y/%m")
    end_month = end_date[:7].replace("-", "/")

    db = get_db()
    try:
        row = db.execute(
            """
            SELECT MAX(date) AS max_date
            FROM chess_com_ratings
            WHERE username = %s AND date BETWEEN %s AND %s
            """,
            (username, start_date, end_date),
        ).fetchone()
        last_date = row["max_date"] if row else None
        last_month = last_date.strftime("%Y/%m") if last_date else None
    finally:
        db.close()

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{CHESS_COM_BASE}/player/{username}/games/archives")
        resp.raise_for_status()
        archives = resp.json()["archives"]
        archives = [url for url in archives if start_month <= url[-7:] <= end_month]
        if last_month:
            archives = [url for url in archives if url[-7:] >= last_month]

        months_fetched = 0
        ratings_upserted = 0
        pending_ratings = []

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

                date_str = datetime.fromtimestamp(end_time, tz=timezone.utc).strftime(
                    "%Y-%m-%d"
                )
                if date_str < start_date or date_str > end_date:
                    continue

                if date_str not in daily_ratings or end_time > daily_ratings[date_str][1]:
                    daily_ratings[date_str] = (rating, end_time)

            for date_str, (rating, _) in daily_ratings.items():
                pending_ratings.append((username, date_str, "rapid", rating))
                ratings_upserted += 1

            months_fetched += 1

        db = get_db()
        try:
            for row in pending_ratings:
                db.execute(
                    """
                    INSERT INTO chess_com_ratings (username, date, time_class, rating)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (username, date, time_class)
                    DO UPDATE SET rating = EXCLUDED.rating
                    """,
                    row,
                )
            db.commit()
        finally:
            db.close()

    return {"months_fetched": months_fetched, "ratings_upserted": ratings_upserted}


def get_ratings(username: str, start_date: str, end_date: str) -> list:
    db = get_db()
    try:
        seed = db.execute(
            """
            SELECT rating
            FROM chess_com_ratings
            WHERE username = %s AND time_class = 'rapid' AND date <= %s
            ORDER BY date DESC
            LIMIT 1
            """,
            (username, start_date),
        ).fetchone()

        rows = db.execute(
            """
            SELECT date, rating
            FROM chess_com_ratings
            WHERE username = %s AND time_class = 'rapid' AND date BETWEEN %s AND %s
            ORDER BY date
            """,
            (username, start_date, end_date),
        ).fetchall()
    finally:
        db.close()

    rating_map = {
        row["date"].isoformat() if hasattr(row["date"], "isoformat") else row["date"]: row[
            "rating"
        ]
        for row in rows
    }

    result = []
    current_rating = seed["rating"] if seed else None
    current_date = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    while current_date <= end:
        date_str = current_date.strftime("%Y-%m-%d")
        if date_str in rating_map:
            current_rating = rating_map[date_str]
        if current_rating is not None:
            result.append({"date": date_str, "rating": current_rating})
        current_date += timedelta(days=1)

    return result
