@echo off
REM [blockchain 담당] 베타/데모용: 서버를 0.0.0.0 으로 켜고 cloudflared 빠른 터널로 외부 공개.
REM 사용: run-public.cmd  → 잠시 후 "https://xxxx.trycloudflare.com" 주소가 뜸. 그 주소를 참가자에게 공유.
REM 주의: 이 창을 닫으면 서버·터널이 꺼짐. PC 잠자기 끄기. 소셜 로그인은 고정 주소(이름 있는 터널) 필요.
cd /d "%~dp0"
set PYTHONUTF8=1
start "SharePie 서버" cmd /k py -3.14 -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
timeout /t 5 /nobreak >nul
echo.
echo  ===== 터널을 여는 중... 아래에 https://....trycloudflare.com 주소가 나오면 그걸 공유하세요 =====
echo.
tools\cloudflared.exe tunnel --url http://127.0.0.1:8000
