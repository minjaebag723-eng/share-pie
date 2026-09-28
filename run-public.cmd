@echo off
REM Share Pie beta server + Cloudflare quick tunnel (docs/BETA-PUBLIC.md, deploy/README.md)
REM Keep both windows open. Closing them stops the server and the tunnel.
cd /d "%~dp0"
set PYTHONUTF8=1
start "SharePie server" cmd /k py -3.14 -m uvicorn deploy.asgi:app --host 0.0.0.0 --port 8000 --workers 1 --timeout-keep-alive 30
timeout /t 8 /nobreak >nul
echo.
echo  ===== Opening tunnel... share the https://....trycloudflare.com address shown below =====
echo.
tools\cloudflared.exe tunnel --url http://127.0.0.1:8000
