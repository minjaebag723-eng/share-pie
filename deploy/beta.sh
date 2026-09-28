#!/usr/bin/env bash
# Share Pie 베타 서버 도우미 (Linux · 도커) — 프로젝트 맨 위 폴더에서: bash deploy/beta.sh <명령>
#   up        새로 빌드해서 켜기 (코드를 바꾼 뒤에도 이것)      down     끄기
#   restart   앱만 다시 켜기                                    logs     앱 로그 보기 (Ctrl+C로 나가기)
#   status    컨테이너 상태 + 서버 응답                          data     베타 데이터 폴더 위치·파일·용량
#   bundle    베타 데이터를 zip으로 → beta-bundles/              backup   운영+베타 데이터 전체 백업 → backups/
#   send <rclone대상>  zip을 만들어 드라이브로 (예: send gdrive:SharePie/beta)
#   chain     에이전트 지갑 잔액 · 가스비 · 정산 몇 건 분량 남았나 (실제 체인일 때)
set -euo pipefail
cd "$(dirname "$0")/.."
DC="docker compose --env-file .env -f deploy/docker-compose.yml"
mkdir -p data beta-data beta-bundles backups
case "${1:-help}" in
  up)      $DC up -d --build && $DC ps ;;
  down)    $DC down ;;
  restart) $DC restart app ;;
  logs)    $DC logs -f --tail=200 app ;;
  status)  $DC ps && $DC exec -T app python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=5).read().decode())" ;;
  data)    $DC exec -T app python deploy/beta_bundle.py --info ;;
  bundle)  $DC exec -T app python deploy/beta_bundle.py --out /app/beta-bundles
           ls -t beta-bundles/*.zip 2>/dev/null | tail -n +25 | xargs -r rm -f      # 최근 24개만 남김
           ls -lh beta-bundles | tail -3 ;;
  send)    [ -n "${2:-}" ] || { echo "사용: bash deploy/beta.sh send gdrive:폴더"; exit 1; }
           $DC exec -T app python deploy/beta_bundle.py --out /app/beta-bundles
           rclone copy "$(ls -t beta-bundles/*.zip | head -1)" "$2" && echo "올림: $2" ;;
  chain)   $DC exec -T app python deploy/chain_bench.py status ;;
  backup)  f="backups/sharepie_$(date +%Y%m%d-%H%M%S).tgz"; tar czf "$f" data beta-data && echo "백업: $f ($(du -h "$f" | cut -f1))" ;;
  *)       sed -n '2,10p' "$0" ;;
esac
