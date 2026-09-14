#!/usr/bin/env bash
# Start the Clipizator web backend and Vite app for access through an SSH tunnel.

set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$PROJECT_DIR/venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing Python environment: $PYTHON"
  echo "Run ./start.sh once to install the project dependencies."
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm was not found. Load your Node/NVM environment, then try again."
  exit 1
fi

if [[ ! -d "$PROJECT_DIR/app/node_modules" ]]; then
  echo "Frontend dependencies are missing. Run: cd $PROJECT_DIR/app && npm install"
  exit 1
fi

cleanup() {
  echo ""
  echo "Stopping Clipizator backend..."
  kill "$BACKEND_PID" 2>/dev/null || true
}

echo "Starting Clipizator backend at http://127.0.0.1:8000"
(
  cd "$PROJECT_DIR/backend"
  exec "$PYTHON" -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload
) &
BACKEND_PID=$!
trap cleanup EXIT INT TERM

echo "Starting Clipizator app at http://127.0.0.1:5173"
echo "Keep this SSH session open, then browse to http://localhost:5173 on Windows."
cd "$PROJECT_DIR/app"
npm run dev -- --host 127.0.0.1
