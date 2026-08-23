@echo off
REM publikclip web dev — starts both backend and frontend
echo.
echo  ╔══════════════════════════════════════╗
echo  ║   publikclip — web dev server        ║
echo  ╚══════════════════════════════════════╝
echo.

@REM REM Install backend and pipeline deps if needed
@REM echo [1/3] Installing Python dependencies (this might take a while on first run)...
@REM cd /d "%~dp0backend"
@REM pip install -r requirements.txt -q 2>nul
@REM cd /d "%~dp0pipeline"
@REM pip install -e . -q 2>nul

REM Start backend in background
echo [2/3] Starting FastAPI backend on :8000...
start "publikclip-backend" cmd /k "cd /d "%~dp0backend" && python run.py"

REM Install frontend deps + start
echo [3/3] Starting React frontend on :5173...
cd /d "%~dp0app"
if not exist node_modules (
    echo    Installing npm packages...
    call npm install
)
echo.
echo  ┌──────────────────────────────────────┐
echo  │  Open http://localhost:5173           │
echo  └──────────────────────────────────────┘
echo.
call npm run dev
