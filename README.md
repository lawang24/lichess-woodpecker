# Chess Woodpecker

Tactical puzzle trainer based on the [Woodpecker Method](https://www.amazon.com/Woodpecker-Method-Axel-Smith/dp/1784830550) — solve the same set of puzzles in repeated cycles to build pattern recognition.

Powered by the [Lichess puzzle database](https://database.lichess.org/#puzzles) (~5.8M puzzles).

## How it works

1. **Create a puzzle set** — pick a target rating and size; puzzles are sampled from the Lichess database with a weighted distribution around your rating.
2. **Solve in cycles** — work through the set on Lichess, marking each puzzle as complete.
3. **Repeat** — start a new cycle and go faster each time.

Tracks cycle history (completion count, duration) and Chess.com rating over time.

## Setup

**Prerequisites:** Python 3.14+, Node 18+, PostgreSQL 16+, [uv](https://github.com/astral-sh/uv)

Add a Postgres connection string in `.env` before starting the backend:

```bash
DATABASE_URL=postgresql://postgres:<password>@127.0.0.1:5432/postgres
```

```bash
# Install dependencies
cd backend && uv sync && cd ..
cd frontend && npm install && cd ..

# Build the compact puzzle catalog (one-time or after puzzles.csv.zst changes)
cd backend && .venv/bin/python build_puzzle_catalog.py && cd ..

# Run both servers
./dev.sh
```

The app runs at `http://localhost:5173` (frontend) with the API at `http://localhost:8000`.
`./dev.sh` enables FastAPI hot reload for the backend by default. Set `UVICORN_RELOAD=0` if you need to disable it.
Puzzle sampling uses memory-mapped NumPy arrays built from `backend/data/puzzles.csv.zst`, so build the compact catalog before creating sets.

For production, build the frontend (`npm run build` in `frontend/`) and the backend serves it directly from `backend/static/`.

## Render

After the production build refactor, `backend/` is the deploy root on Render.

- **Runtime:** `Python 3`
- **Root Directory:** `backend`
- **Build Command:** `cd ../frontend && npm ci && npm run build && cd ../backend && uv sync && .venv/bin/python build_puzzle_catalog.py`
- **Start Command:** `uv run python main.py`

Set `DATABASE_URL` from a Render Postgres instance.

## Stack

- **Backend:** FastAPI, PostgreSQL, NumPy
- **Frontend:** React, Vite, Chart.js
- **Data:** Lichess puzzle DB (stripped to ID + rating, ~32MB compressed)
