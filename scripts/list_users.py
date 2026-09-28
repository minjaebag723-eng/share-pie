"""이 서버에 가입된 계정 보기: py scripts/list_users.py [검색어]
친구 추가에서 'Pie ID를 쓰는 사용자가 없어요'가 뜨면, 친구가 정말 이 서버(이 데이터 폴더)에 가입했는지 확인하세요."""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import config, store  # noqa: E402

q = (sys.argv[1] if len(sys.argv) > 1 else "").lstrip("@").lower()
users = [u for u in store.users() if not q or q in (u.get("pie_id") or "") or q in u["name"] or q in u["email"].lower()]
print(f"데이터 폴더: {config.DATA_DIR}")
print(f"가입자 {len(store.users())}명" + (f" · ‘{q}’ 검색 {len(users)}명" if q else ""))
for u in sorted(users, key=lambda u: u["created_at"]):
    local, _, dom = u["email"].partition("@")
    mail = local[:2] + "*" * max(1, len(local) - 2) + "@" + dom
    soc = ",".join(u.get("social") or {})
    print(f"  @{u.get('pie_id') or '-':<20} {u['name']:<8} ({u['short']})  {mail:<28} "
          f"{datetime.fromtimestamp(u['created_at']).strftime('%m-%d %H:%M')}" + (f"  소셜:{soc}" if soc else ""))
if q and not users:
    print("→ 없어요. 친구가 다른 주소(다른 PC의 localhost, 예전 터널 주소)에서 가입했거나, 서버를 새 폴더에서 켜기 전 데이터에 있을 수 있어요.")
