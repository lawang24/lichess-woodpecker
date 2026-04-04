#!/bin/bash

# Start both frontend and backend dev servers
# Kill both processes when this script exits (Ctrl+C)
trap 'kill 0' EXIT

cd "$(dirname "$0")"

# Backend
(cd backend && uv run python main.py) &

# Frontend
(cd frontend && npm run dev) &

wait
