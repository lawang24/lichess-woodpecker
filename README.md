# Lichess Woodpecker

Based on [The Woodpecker Method](https://qualitychess.co.uk/products/improvement/327/the_woodpecker_method_by_axel_smith_and_hans_tikkanen/) by GMs Smith and Tikkanen.

TLDR: Solve a fixed set of Lichess puzzles, then repeat it across six faster cycles: 4 weeks, 2 weeks, 1 week, 4 days, 2 days, and 1 day until the patterns becomes automatic. Automatically tracks and vizualises progress so you don't have to manually. 

Lightweight and reuses lichess's application where possible -  making it easily cloned, modified, and locally hosted  

<video src="docs/assets/playthrough.mov" controls width="100%" title="Lichess Woodpecker playthrough"></video>

**Try it here:** [https://lichess-woodpecker.onrender.com/](https://lichess-woodpecker.onrender.com/)

## Basic Guide

1. **Create a tailored puzzle set** - choose a target puzzle rating and quantity; puzzles are sampled from the Lichess database +200/-200 around that rating.
2. **Solve on Lichess** - each puzzle opens on `lichess.org/training`, while this app tracks the ones you've opened / completed.
3. **Repeat in cycles** - train the same set across faster Woodpecker cycles: 4 weeks, 2 weeks, 1 week, 4 days, 2 days, and 1 day.
4. **Review history** - see completion count, duration, and cycle progress over time.

## Local Development Setup

**Prerequisites:** Python 3.14+, Node 18+, PostgreSQL 16+, [uv](https://github.com/astral-sh/uv)

Add the required backend settings in `.env` before starting:

```bash
cp .env.example .env
```

Edit `DATABASE_URL` for your local PostgreSQL instance. `dev.sh` defaults `APP_BASE_URL` to `http://localhost:5173`, `SESSION_SECRET` to `dev-session-secret`, and `LICHESS_CLIENT_ID` to `lichess-woodpecker-local` if they are not set. In production, set `SESSION_SECRET` explicitly and use a stable `LICHESS_CLIENT_ID` for the deployment.

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

## Stack

- **Backend:** FastAPI, PostgreSQL, Authlib
- **Frontend:** React, Vite, Chart.js, 
- **Data:** Lichess puzzle DB (stripped to ID + rating, ~32MB compressed)
