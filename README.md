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

# Run both servers
./dev.sh
```

The app runs at `http://localhost:5173` (frontend) with the API at `http://localhost:8000`.

For production, build the frontend (`npm run build` in `frontend/`) and the backend serves it directly.

## Stack

- **Backend:** FastAPI, PostgreSQL, Pandas
- **Frontend:** React, Vite, Chart.js
- **Data:** Lichess puzzle DB (stripped to ID + rating, ~32MB compressed)
