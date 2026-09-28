#!/bin/bash
# JAAL — One-command dev startup for Linux/macOS
# Usage: ./run.sh
# Starts backend (port 8000) + frontend (port 5173)

set -e

echo "=========================================="
echo " JAAL — Fraud Network Intelligence System"
echo "=========================================="
echo

# Check for .env
if [ ! -f ".env" ]; then
    echo "[WARN] .env not found. Copying .env.example ..."
    cp .env.example .env
    echo "[WARN] Edit .env and set BOB_API_KEY, or set FORCE_FALLBACK=1 for offline mode."
    echo
fi

mkdir -p logs

# Start backend
echo "[1/2] Starting backend (uvicorn) on http://localhost:8000 ..."
uvicorn backend.main:app --reload --port 8000 > logs/backend.log 2>&1 &
BACKEND_PID=$!
echo "      Backend PID: $BACKEND_PID"

# Wait a moment
sleep 2

# Start frontend
echo "[2/2] Starting frontend (Vite) on http://localhost:5173 ..."
cd frontend
npm run dev > ../logs/frontend.log 2>&1 &
FRONTEND_PID=$!
cd ..
echo "      Frontend PID: $FRONTEND_PID"

echo
echo "Both services started."
echo "Open: http://localhost:5173"
echo
echo "Backend  logs: logs/backend.log"
echo "Frontend logs: logs/frontend.log"
echo
echo "Press Ctrl+C to stop both services."

# Wait for Ctrl+C and kill both
trap "echo 'Stopping...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT
wait
