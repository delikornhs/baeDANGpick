"""
KIND '설정/환매접수 일시중지 안내' 공시에서 다음 분배 일정을 알아낸다.

  python -X utf8 kind_schedule.py                  # 최근 30일 공시 기준
  python -X utf8 kind_schedule.py --days 60        # 조회 범위 조정
  python -X utf8 kind_schedule.py --from 2026-03-01 --to 2026-07-31

■ 원리
  분배금 확정 공시보다 5~9일 먼저 이 안내가 올라오고, 여기에
  '설정/환매 청구접수 중지기간(시작일~종료일)'이 적혀 있다.
  수익자 명부를 확정하는 동안 기관의 설정/환매를 막는 것인데,
  주식·ETF 모두 T+2 결제이므로
      중지기간 종료일 = 명부에 오르는 마지막 매수일 = 최종매수일
  이 된다. 배당락일 = +1영업일, 기준일 = +2영업일.

  2026-03~07 8개 회차 전부 실제 기준일과 일치함을 확인했다.

■ 한계
  배당락일·기준일은 아직 오지 않은 날이라 실제 거래일 데이터가 없어
  주말만 건너뛰어 계산한다. 공휴일이 끼면 하루씩 밀릴 수 있으므로,
  분배금 공시가 나오면 그 안의 실제 기준일과 대조해 확정할 것.
"""

import argparse
import collections
import re
import sys
from datetime import date, timedelta

import kind_client as kc

sys.stdout.reconfigure(encoding="utf-8")

REPORT_NM = "ETF이익금분배 수익자 확정"
TITLE_RX = r"설정/환매"
WD = "월화수목금토일"


def next_weekday(d: date) -> date:
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def fmt(d: date) -> str:
    return f"{d.isoformat()}({WD[d.weekday()]})"


def main():
    ap = argparse.ArgumentParser(description="KIND 분배 일정 파악")
    ap.add_argument("--days", type=int, default=30, help="오늘 기준 최근 N일 (기본 30)")
    ap.add_argument("--from", dest="frm", help="YYYY-MM-DD")
    ap.add_argument("--to", dest="to", help="YYYY-MM-DD")
    args = ap.parse_args()

    today = date.today()
    frm = args.frm or (today - timedelta(days=args.days)).isoformat()
    to = args.to or today.isoformat()

    print("=" * 60)
    print(f"📅 분배 일정 공시 검색: {frm} ~ {to}")
    print("=" * 60)

    rows = kc.search_disclosures(REPORT_NM, frm, to, title_filter=TITLE_RX)
    if not rows:
        print("검색 결과가 없습니다.")
        return
    print(f"공시 {len(rows)}건 발견 — 본문에서 중지기간 추출 중…\n")

    # (시작일, 종료일) → 등장 횟수. 여러 운용사가 같은 회차를 각각 공시하므로 표가 겹친다.
    periods = collections.Counter()
    failed = 0
    for r in rows:
        try:
            doc, _ = kc.fetch_document(r["acptno"])
            if not doc:
                failed += 1
                continue
            txt = kc.doc_to_text(doc)
            for st, en in re.findall(r"(20\d\d-\d\d-\d\d)\s+(20\d\d-\d\d-\d\d)", txt):
                periods[(st, en)] += 1
        except Exception:
            failed += 1

    if not periods:
        print("중지기간을 찾지 못했습니다.")
        return

    # 종료일 기준으로 회차를 묶는다 (같은 회차면 종료일이 같음).
    # 한 공시 문서에 여러 회차가 섞여 있고 비정기 상품은 자기만의 일정을 갖기 때문에,
    # 종목 수(등장 횟수)가 적은 종료일은 비정기로 보고 주요 회차와 구분한다.
    by_end = collections.defaultdict(int)
    for (st, en), n in periods.items():
        by_end[en] += n
    # 정규 회차는 수십~수백 종목(월중 46~51, 월말 100~500)인 반면
    # 비정기는 1~10종목 수준이라 절대 기준으로 갈린다.
    # 최대값 대비 비율로 잡으면 월말(수백)에 눌려 정상 월중이 오탐된다.
    THRESH = 15

    print(f"{'회차':<10}{'최종매수일':<18}{'배당락일':<18}{'기준일':<18}{'종목수':>6}  상태")
    print("-" * 86)

    results = []
    for en in sorted(by_end):
        cnt = by_end[en]
        last_buy = date.fromisoformat(en)
        ex = next_weekday(last_buy)
        rec = next_weekday(ex)
        timing = "월중" if rec.day <= 20 else "월말"
        state = "지난 회차" if last_buy < today else ("오늘 마감" if last_buy == today else "예정")
        major = cnt >= THRESH
        if not major:
            state += " · 비정기 추정"
        print(f"{timing:<10}{fmt(last_buy):<18}{fmt(ex):<18}{fmt(rec):<18}{cnt:>6}  {state}")
        results.append((timing, last_buy, ex, rec, state, major))

    upcoming = [r for r in results if r[1] >= today and r[5]]
    if upcoming:
        print("\n" + "=" * 60)
        print("📌 다가오는 회차 — index.html CONFIRMED_SCHEDULE 에 넣을 형태")
        print("=" * 60)
        for timing, lb, ex, rec, _s, _m in upcoming:
            print(f"  // {timing} 회차")
            print(f"  {{date:'{lb}', type:'buy',    label:'최종매수',     ex:'{ex}'}},")
            print(f"  {{date:'{ex}', type:'ex',     label:'배당락',       ex:'{ex}'}},")
            print(f"  {{date:'{rec}', type:'record', label:'기준일({timing})', ex:'{ex}'}},")
        print("\n※ 월중·월말은 독립 회차이므로 해당 회차 3줄만 교체하고 나머지는 남겨둘 것.")
        print("※ 배당락일·기준일은 주말만 반영한 계산값. 공휴일이 끼면 분배금 공시의")
        print("   실제 기준일과 다를 수 있으므로 공시 후 대조할 것.")

    if failed:
        print(f"\n⚠️ 문서 조회 실패 {failed}건")


if __name__ == "__main__":
    main()
