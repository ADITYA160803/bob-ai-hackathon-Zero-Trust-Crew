@echo off
REM JAAL — One-command dev startup for Windows
REM Usage: run.bat
REM Starts backend (port 8000) + frontend (port 5173)

echo ==========================================
echo  JAAL — Fraud Network Intelligence System
echo ==========================================
echo.

REM Check for .env
IF NOT EXIST ".env" (
    echo [WARN] .env not found. Copying .env.example ...
    copy .env.example .env
    echo [WARN] Edit .env and set BOB_API_KEY, or set FORCE_FALLBACK=1 for offline mode.
    echo.
)

REM Start backend in background
echo [1/2] Starting backend (uvicorn) on http://localhost:8000 ...
start "JAAL Backend" /B cmd /c "uvicorn backend.main:app --reload --port 8000 > logs\backend.log 2>&1"

REM Wait a moment for backend to start
timeout /t 2 /nobreak > nul

REM Start frontend in background
echo [2/2] Starting frontend (Vite) on http://localhost:5173 ...
start "JAAL Frontend" /B cmd /c "cd frontend && npm run dev > ..\logs\frontend.log 2>&1"

echo.
echo Both services starting. Open http://localhost:5173 in your browser.
echo Backend logs : logs\backend.log
echo Frontend logs: logs\frontend.log
echo.
echo Press Ctrl+C or close this window to stop.
pause
