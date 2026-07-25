"""
KIND에서 ETF 분배금 공시(XLS)를 자동 수집한다.

  python -X utf8 kind_fetch.py                     # 지난달 1일 ~ 오늘 (기본)
  python -X utf8 kind_fetch.py --month 2026-07     # 특정 월만
  python -X utf8 kind_fetch.py --from 2026-01 --to 2026-06   # 과거 backfill

■ 기본 범위가 왜 '지난달 1일부터'인가
  비정기 분배 공시는 월중·월말과 무관한 날짜에 툭툭 올라온다.
  한 달 범위만 보면 '월말 수집 이후 ~ 다음 달 월중 수집 전' 구간에 구멍이 생기므로
  매번 지난달까지 겹쳐서 훑는다. 이미 받은 파일은 건너뛰므로 비용은 거의 없다.

■ 파일명을 KIND가 주는 그대로 저장하는 이유
  etf_data_processor.py 가 파일명에서 공시일(notice_date)을 추출해
  '공시일 전일 종가 기준 분배율' 계산에 사용한다. 형식을 바꾸면 분배율이 틀어진다.
"""

import argparse
import re
import sys
from datetime import date
from pathlib import Path

import kind_client as kc

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "data" / "raw"

REPORT_NM = "ETF이익금분배신고"
TITLE_RX = r"ETF이익금분배신고\(분배금안내\)"


def month_folder(notice_date: str) -> str:
    """'2026-04-28' → '26년 4월' (기존 폴더 명명 규칙)"""
    y, m, _ = notice_date.split("-")
    return f"{y[2:]}년 {int(m)}월"


def parse_records(content: str) -> list:
    """etf_data_processor.parse_xls 와 동일한 추출 로직 (수집 결과 보고용)."""
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", content, re.DOTALL | re.IGNORECASE):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL | re.IGNORECASE)
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        if (len(cells) >= 5 and cells[0].startswith("KR") and cells[1]
                and re.match(r"^\d+$", cells[4])):
            out.append({"isin": cells[0], "name": cells[1], "ex_date": cells[2],
                        "dist": int(cells[4])})
    return out


def default_range() -> tuple:
    today = date.today()
    start = date(today.year - 1, 12, 1) if today.month == 1 \
        else date(today.year, today.month - 1, 1)
    return start.isoformat(), today.isoformat()


def main():
    ap = argparse.ArgumentParser(description="KIND ETF 분배금 공시 수집")
    ap.add_argument("--month", help="YYYY-MM (해당 월만)")
    ap.add_argument("--from", dest="frm", help="YYYY-MM (시작 월)")
    ap.add_argument("--to", dest="to", help="YYYY-MM (종료 월)")
    ap.add_argument("--dry-run", action="store_true", help="목록만 확인하고 저장하지 않음")
    args = ap.parse_args()

    if args.month:
        y, m = map(int, args.month.split("-"))
        frm = date(y, m, 1).isoformat()
        to = (date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)).replace(day=1)
        to = (to.toordinal() - 1)
        to = date.fromordinal(to).isoformat()
    elif args.frm:
        y, m = map(int, args.frm.split("-"))
        frm = date(y, m, 1).isoformat()
        if args.to:
            y2, m2 = map(int, args.to.split("-"))
            nxt = date(y2 + 1, 1, 1) if m2 == 12 else date(y2, m2 + 1, 1)
            to = date.fromordinal(nxt.toordinal() - 1).isoformat()
        else:
            to = date.today().isoformat()
    else:
        frm, to = default_range()

    print("=" * 60)
    print(f"📡 KIND 분배금 공시 검색: {frm} ~ {to}")
    print("=" * 60)

    rows = kc.search_disclosures(REPORT_NM, frm, to, title_filter=TITLE_RX)
    if not rows:
        print("검색 결과가 없습니다.")
        return
    print(f"공시 {len(rows)}건 발견\n")

    saved, skipped, failed = [], [], []
    all_records = {}

    for r in rows:
        try:
            doc, file_name = kc.fetch_document(r["acptno"])
            if not doc or not file_name:
                failed.append(f"{r['date']} {r['corp']} (문서 없음)")
                continue

            notice = re.search(r"(\d{4})[.\-](\d{2})[.\-](\d{2})", file_name)
            notice_date = f"{notice.group(1)}-{notice.group(2)}-{notice.group(3)}" \
                if notice else r["date"]

            folder = RAW_DIR / month_folder(notice_date)
            path = folder / f"{file_name}.xls"

            recs = parse_records(doc)
            for x in recs:
                all_records[(x["isin"], x["ex_date"])] = x

            if path.exists():
                skipped.append(path.name)
                continue
            if args.dry_run:
                saved.append(f"(dry-run) {path.name}  {len(recs)}건")
                continue

            folder.mkdir(parents=True, exist_ok=True)
            path.write_text(doc, encoding="utf-8")
            saved.append(f"{path.name}  {len(recs)}건")
        except Exception as e:
            failed.append(f"{r['date']} {r['corp']} — {type(e).__name__}: {e}")

    print(f"✅ 신규 저장 {len(saved)}건 / 이미 있음 {len(skipped)}건 / 실패 {len(failed)}건\n")
    for s in saved:
        print(f"  + {s}")
    if failed:
        print("\n⚠️ 실패:")
        for f in failed:
            print(f"  - {f}")

    # 기준일 분포 (월중/월말/비정기 파악용)
    if all_records:
        by_ex = {}
        for (_, ex), _v in all_records.items():
            by_ex[ex] = by_ex.get(ex, 0) + 1
        print(f"\n📅 수집된 기준일 분포 (총 {len(all_records)}건)")
        # 정규 회차는 수십~수백 종목(월중 46~51, 월말 100~500), 비정기는 1~10종목 수준이라
        # 절대 기준으로 갈린다. 최대값 대비 비율로 잡으면
        #  - 월말(수백)에 눌려 정상 월중이 오탐되고
        #  - 여러 달을 함께 수집할 때 다른 달 회차와 비교돼 또 오탐된다.
        THRESH = 15
        for ex in sorted(by_ex):
            cnt = by_ex[ex]
            t = "월중" if int(ex[8:10]) <= 20 else "월말"
            tag = "  ← 비정기 추정" if cnt < THRESH else ""
            print(f"   {ex}  {cnt:>4}건  {t}{tag}")
        print("\n※ 월중/월말/비정기 최종 분류는 프로세서가 주기(freq)를 보고 결정합니다.")

    if saved and not args.dry_run:
        print("\n다음 단계: python -X utf8 etf_data_processor.py")


if __name__ == "__main__":
    main()
