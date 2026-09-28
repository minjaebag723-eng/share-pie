"""베타 데이터 폴더를 zip 하나로 묶는다 (서버를 끄지 않아도 됨).

  python deploy/beta_bundle.py                               → ./beta-bundles/sharepie-beta-data_<버전>_<시각>.zip
  python deploy/beta_bundle.py --out D:\\받은데이터             → 원하는 폴더에
  python deploy/beta_bundle.py --rclone gdrive:SharePie/beta  → rclone으로 구글 드라이브 등에 바로 올리기 (rclone config로 연결해 둔 경우)
  python deploy/beta_bundle.py --info                        → 폴더 위치 · 파일 · 용량만 보기
도커로 띄운 서버면:  docker compose --env-file .env -f deploy/docker-compose.yml exec app python deploy/beta_bundle.py --out /app/beta-data-bundles
서버와 같은 .env(DATA_DIR·BETA_DATA_DIR)를 읽는다. 계정·비밀번호가 든 db.json은 묶지 않는다.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from agent import beta, config  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Share Pie 베타 데이터 묶기")
    ap.add_argument("--out", help="zip을 둘 폴더 (기본 ./beta-bundles)")
    ap.add_argument("--rclone", help="rclone 대상 (예: gdrive:SharePie/beta)")
    ap.add_argument("--info", action="store_true", help="폴더 위치·파일·용량만 출력")
    a = ap.parse_args()
    if a.info:
        print(json.dumps(beta.storage_info(), ensure_ascii=False, indent=1))
        return
    zp = beta.bundle_file(a.out or ROOT / "beta-bundles")
    man = json.loads(beta.MANIFEST.read_text(encoding="utf-8"))
    print(f"데이터 폴더: {config.BETA_DATA_DIR}")
    print(f"묶음: {zp}  ({zp.stat().st_size:,} bytes)")
    for name, f in man["files"].items():
        lines = "-" if f["lines"] is None else f"{f['lines']:,}줄"
        print(f"  {name:<20} {lines:>10}  {f['bytes']:>12,} bytes")
    if a.rclone:
        if not shutil.which("rclone"):
            sys.exit("rclone이 없어요 → https://rclone.org/install/ 설치 후 `rclone config`로 드라이브를 연결해 주세요")
        subprocess.run(["rclone", "copy", str(zp), a.rclone], check=True)
        print(f"올림: {a.rclone}/{zp.name}")


if __name__ == "__main__":
    main()
