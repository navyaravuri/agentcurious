#!/usr/bin/env bash
set -e

# ── Load .env if key not already in environment ───────────────────────────────
if [ -f "backend/.env" ]; then
  # shellcheck disable=SC1091
  set -o allexport
  source backend/.env
  set +o allexport
fi

# ── Check for GEMINI_API_KEY ──────────────────────────────────────────────────
if [ -z "$GEMINI_API_KEY" ] || [ "$GEMINI_API_KEY" = "your_gemini_api_key_here" ]; then
  echo ""
  echo "  GEMINI_API_KEY is not set."
  echo ""
  echo "  To fix this:"
  echo "    1. Copy backend/.env.example to backend/.env"
  echo "       cp backend/.env.example backend/.env"
  echo "    2. Open backend/.env and replace 'your_gemini_api_key_here' with your key"
  echo "    3. Export it in your shell:"
  echo "       export GEMINI_API_KEY=your_actual_key"
  echo "    4. Re-run this script"
  echo ""
  exit 1
fi

# ── Cleanup on exit ───────────────────────────────────────────────────────────
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  echo ""
  echo "Shutting down..."
  [ -n "$BACKEND_PID" ]  && kill "$BACKEND_PID"  2>/dev/null
  [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null
  exit 0
}

trap cleanup INT TERM

# ── Start backend ─────────────────────────────────────────────────────────────
echo "Starting backend..."
(cd backend && venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000) &
BACKEND_PID=$!

# ── Start frontend ────────────────────────────────────────────────────────────
echo "Starting frontend..."
(cd frontend && python3 -m http.server 3000) &
FRONTEND_PID=$!

# ── Ready ─────────────────────────────────────────────────────────────────────
echo ""
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:3000"
echo ""
echo "  Press Ctrl+C to stop both servers."
echo ""

wait
