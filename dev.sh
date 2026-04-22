#!/bin/bash

# Start both frontend and backend dev servers
# Kill both processes when this script exits (Ctrl+C)
trap 'kill 0' EXIT

cd "$(dirname "$0")"

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

if [ -f .env.local ]; then
  set -a
  source .env.local
  set +a
fi

if [ -z "${DATABASE_URL:-}" ]; then
  echo "DATABASE_URL is required" >&2
  exit 1
fi

export FRONTEND_DEV_URL="${FRONTEND_DEV_URL:-http://localhost:5173}"
export APP_BASE_URL="${APP_BASE_URL:-$FRONTEND_DEV_URL}"
export SESSION_SECRET="${SESSION_SECRET:-dev-session-secret}"
export LICHESS_CLIENT_ID="${LICHESS_CLIENT_ID:-chess-woodpecker-local}"

# Backend
(cd backend && UVICORN_RELOAD="${UVICORN_RELOAD:-1}" uv run python main.py) &

# Frontend
(cd frontend && npm run dev) &

wait
