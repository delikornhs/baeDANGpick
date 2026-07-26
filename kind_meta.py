"""
data/raw 에 있는데 메타 캐시(etf_meta.json)에는 없는 신규 종목의 메타를 채운다.

  python -X utf8 kind_meta.py            # 부족한 것만 조회
  python -X utf8 kind_meta.py --dry-run  # 대상만 확인

■ 왜 필요한가
  신규 상장 ETF가 처음 분배할 때, 프로세서 기본 실행 경로는 메타 캐시를 '읽기만' 한다.
  캐시를 채우는 건 `--prices-only`(매일 종가 워크플로)뿐이라,
  첫 분배 당일에는 상장일·기초지수·상품설명이 빈 채로 사이트에 노출되고
  다음 날 종가 워크플로가 돌아야 채워진다(약 23시간 공백).

  이 스크립트를 프로세서 **실행 전에** 돌려 캐시를 미리 채우면 그 공백이 사라진다.
  이미 캐시에 있는 종목은 건너뛰므로 평소에는 거의 즉시 끝난다.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "data" / "raw"
META_FILE = BASE_DIR / "data" / "output" / "etf_meta.json"


def codes_in_raw() -> dict:
    """data/raw 전체에서 (종목코드 → 종목명) 수집"""
    found = {}
    for path in sorted(RAW_DIR.rglob("*.xls")) + sorted(RAW_DIR.rglob("*.XLS")):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", content, re.DOTALL | re.IGNORECASE):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL | re.IGNORECASE)
            cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if (len(cells) >= 5 and cells[0].startswith("KR") and cells[1]
                    and re.match(r"^\d+$", cells[4])):
                found[cells[0][3:9]] = cells[1]
    return found


def main():
    ap = argparse.ArgumentParser(description="신규 종목 메타 보충")
    ap.add_argument("--dry-run", action="store_true", help="대상만 출력하고 조회하지 않음")
    args = ap.parse_args()

    all_codes = codes_in_raw()
    if not all_codes:
        print("data/raw 에서 종목을 찾지 못했습니다.")
        return 0

    cache = {}
    if META_FILE.exists():
        with open(META_FILE, encoding="utf-8") as f:
            cache = json.load(f)

    missing = {c: n for c, n in all_codes.items() if c not in cache}

    print(f"data/raw 종목 {len(all_codes)}개 / 메타 캐시 {len(cache)}개")
    if not missing:
        print("✅ 메타가 없는 신규 종목 없음 — 할 일 없음")
        return 0

    print(f"🆕 메타 없는 신규 종목 {len(missing)}개")
    for c, n in list(missing.items())[:20]:
        print(f"   {c}  {n[:40]}")
    if len(missing) > 20:
        print(f"   … 외 {len(missing)-20}개")

    if args.dry_run:
        print("\n(dry-run — 조회하지 않음)")
        return 0

    # 프로세서의 조회 함수를 재사용한다. 기존 캐시를 읽어 병합 후 저장하므로 안전하다.
    import etf_data_processor as proc
    proc.fetch_etf_meta(list(missing.keys()))

    with open(META_FILE, encoding="utf-8") as f:
        after = json.load(f)
    still = [c for c in missing if c not in after]
    filled = len(missing) - len(still)
    print(f"\n✅ {filled}개 메타 보충 완료")
    if still:
        print(f"⚠️ {len(still)}개는 조회 실패 (다음 날 종가 워크플로가 재시도): {still[:10]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
