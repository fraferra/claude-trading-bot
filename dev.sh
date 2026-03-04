#!/usr/bin/env bash
# Start both FastAPI backend and Vite frontend dev server.
# Usage: ./dev.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

cleanup() {
  echo ""
  echo "Shutting down..."
  kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
  wait $BACKEND_PID $FRONTEND_PID 2>/dev/null
  echo "Done."
}
trap cleanup EXIT INT TERM

# Backend
echo "Starting backend on http://127.0.0.1:8000 ..."
.venv/bin/trading-bot serve &
BACKEND_PID=$!

# Give backend a moment to start
sleep 2

# Frontend (--host 127.0.0.1 forces IPv4 to avoid nginx conflicts)
echo "Starting frontend on http://127.0.0.1:5173 ..."
cd frontend && npx vite --host 127.0.0.1 &
FRONTEND_PID=$!
cd "$SCRIPT_DIR"

echo ""
echo "========================================="
echo "  Dashboard:  http://127.0.0.1:5173"
echo "  API:        http://127.0.0.1:8000/api"
echo "  Press Ctrl+C to stop both"
echo "========================================="
echo ""

wait
