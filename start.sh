#!/usr/bin/env bash
# publikclip web dev — starts both backend and frontend

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo " ╔══════════════════════════════════════╗"
echo " ║   publikclip — web dev server        ║"
echo " ╚══════════════════════════════════════╝"
echo ""

# Install backend and pipeline deps
echo "[1/3] Installing Python dependencies (this might take a while on first run)..."
cd "$DIR/backend"
pip install -r requirements.txt -q 2>/dev/null || pip3 install -r requirements.txt -q
cd "$DIR/pipeline"
pip install -e . -q 2>/dev/null || pip3 install -e . -q

# Start backend in background
echo "[2/3] Starting FastAPI backend on :8000..."
python run.py &
BACKEND_PID=$!
trap "kill $BACKEND_PID 2>/dev/null" EXIT

# Install frontend deps + start
echo "[3/3] Starting React frontend on :5173..."
cd "$DIR/app"
[ ! -d node_modules ] && npm install
echo ""
echo " ┌──────────────────────────────────────┐"
echo " │  Open http://localhost:5173           │"
echo " └──────────────────────────────────────┘"
echo ""
npm run dev
