#!/usr/bin/env bash
# Share Pie 베타 서버 — 새 Ubuntu 서버(AWS Lightsail 등)에서 한 번만. 코드 폴더(완성본) 맨 위에서:
#   sudo bash deploy/setup_server.sh
# 하는 일: 도커 설치 · 시간대(서울) · 스왑 2GB · .env 만들기(질문 4개 + 무작위 키 자동) · 매일 백업/매시간 데이터 묶기 예약 · 서버 켜기
# 다시 실행해도 안전해요 (.env가 있으면 그대로 둠).
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "sudo bash deploy/setup_server.sh 로 실행해 주세요"; exit 1; }
cd "$(dirname "$0")/.."
ROOT=$(pwd)
[ -f requirements.txt ] && [ -d agent ] || { echo "Share Pie 코드 폴더(맨 위)에서 실행해 주세요"; exit 1; }

echo "== 1/5 도커"
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh
docker compose version >/dev/null 2>&1 || { echo "docker compose 플러그인이 없어요: sudo apt install -y docker-compose-plugin"; exit 1; }
[ -n "${SUDO_USER:-}" ] && usermod -aG docker "$SUDO_USER" || true

echo "== 2/5 시간대 · 스왑"
timedatectl set-timezone Asia/Seoul 2>/dev/null || true
if ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
mkdir -p data beta-data beta-bundles backups

echo "== 3/5 .env"
set_env() {   # 키 값 — 있으면 바꾸고 없으면 추가
  local v; v=$(printf '%s' "$2" | sed -e 's/[\/&|]/\\&/g')
  if grep -q "^$1=" .env; then sed -i "s|^$1=.*|$1=$v|" .env; else printf '%s=%s\n' "$1" "$2" >> .env; fi
}
if [ ! -f .env ]; then
  cp deploy/.env.beta.example .env
  IP=$(curl -fsS --max-time 5 https://checkip.amazonaws.com 2>/dev/null || true)
  DEF=":80"; [ -n "$IP" ] && DEF="$(echo "$IP" | tr . -).sslip.io"
  read -rp "접속 주소 — 도메인이 없으면 그냥 Enter ($DEF): " SITE; SITE=${SITE:-$DEF}
  read -rp "Kiln API 키 (sk-bk-…): " KILN
  read -rp "쇼핑 검색 SerpApi 키 (없으면 그냥 Enter): " SERPAPI
  read -rp "관리자 이메일 (베타 데이터를 볼 계정, 쉼표로 여러 개): " ADMINS
  set_env SITE_ADDRESS "$SITE"
  [ "$SITE" != ":80" ] && set_env PUBLIC_BASE_URL "https://$SITE"
  set_env KILN_API_KEY "$KILN"
  set_env BETA_ADMIN_EMAILS "$ADMINS"
  [ -n "$SERPAPI" ] && set_env SERPAPI_API_KEY "$SERPAPI"
  set_env BETA_EXPORT_KEY "$(openssl rand -hex 16)"
  set_env BETA_SALT "$(openssl rand -hex 16)"
  chmod 600 .env
  echo "  .env를 만들었어요 (데이터 내려받기 키: $(grep '^BETA_EXPORT_KEY=' .env | cut -d= -f2))"
  echo "  블록체인 값은 nano .env 의 [블록체인] 칸에 — 비워 두면 모의 체인"
else
  echo "  .env가 이미 있어요 — 그대로 써요"
fi

echo "== 4/5 백업 · 데이터 묶기 예약 (매일 04:00 백업 · 매시간 5분 zip)"
( crontab -l 2>/dev/null | grep -v '# sharepie-beta' || true
  echo "0 4 * * * cd $ROOT && bash deploy/beta.sh backup >> $ROOT/backups/cron.log 2>&1 # sharepie-beta"
  echo "5 * * * * cd $ROOT && bash deploy/beta.sh bundle >> $ROOT/backups/cron.log 2>&1 # sharepie-beta" ) | crontab -

echo "== 5/5 서버 켜기 (처음엔 3~5분)"
bash deploy/beta.sh up
SITE=$(grep '^SITE_ADDRESS=' .env | cut -d= -f2)
echo
echo "완료 → https://$SITE   (도메인 없이 :80이면 http://서버IP)"
echo "상태 bash deploy/beta.sh status · 로그 bash deploy/beta.sh logs · 체인 bash deploy/beta.sh chain · 데이터 bash deploy/beta.sh data"
