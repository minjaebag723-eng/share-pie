@echo off
REM Share Pie beta server (Windows, no Docker). Fill .env first, then double-click this file.
REM Closing this window stops the server. For outside access: cloudflared tunnel --url http://localhost:8000
cd /d "%~dp0\.."
set PYTHONUTF8=1
py -3.14 -m pip install -r requirements.txt -r deploy\requirements-server.txt
py -3.14 -m uvicorn deploy.asgi:app --host 0.0.0.0 --port 8000 --workers 1 --timeout-keep-alive 30
pause
