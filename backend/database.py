import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "woodpecker.db")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS puzzle_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            target_rating INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS puzzle_set_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            set_id INTEGER NOT NULL REFERENCES puzzle_sets(id) ON DELETE CASCADE,
            puzzle_id TEXT NOT NULL,
            rating INTEGER,
            position INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cycles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            set_id INTEGER NOT NULL REFERENCES puzzle_sets(id) ON DELETE CASCADE,
            cycle_number INTEGER NOT NULL,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            completed_count INTEGER NOT NULL DEFAULT 0,
            solved_count INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS cycle_completions (
            cycle_id INTEGER NOT NULL REFERENCES cycles(id) ON DELETE CASCADE,
            puzzle_id TEXT NOT NULL,
            completed_at REAL NOT NULL,
            PRIMARY KEY (cycle_id, puzzle_id)
        );

        CREATE TABLE IF NOT EXISTS chess_com_ratings (
            username TEXT NOT NULL,
            date TEXT NOT NULL,
            time_class TEXT NOT NULL,
            rating INTEGER NOT NULL,
            UNIQUE(username, date, time_class)
        );
    """)
    # Migrations
    cols = [row[1] for row in conn.execute("PRAGMA table_info(puzzle_sets)").fetchall()]
    if "target_rating" not in cols:
        conn.execute("ALTER TABLE puzzle_sets ADD COLUMN target_rating INTEGER")

    conn.commit()
    conn.close()
