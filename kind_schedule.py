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

■ 정규 회차 판정
  기준일이 그 달 15일(휴장이면 직전 영업일) 또는 마지막 영업일에 정확히
  붙으면 정규 회차로 본다. 명부확정일은 운용사끼리 공유하므로
  공시가 한 건만 올라와도 판정된다 — 종목수를 기다릴 필요가 없다.

■ 영업일 계산
  krx_calendar.py(한국거래소 휴장일)를 쓴다. 2026-10-12 이전에는 주말만
  건너뛰어 공휴일이 끼면 하루씩 밀렸다. 라이브러리가 모르는 임시공휴일이
  생기면 여전히 어긋날 수 있어, 패턴에 안 맞지만 규모가 큰 회차는
  '확인필요'로 따로 출력한다.

■ 자동 반영
  달력 반영과 일정 뉴스레터는 auto_schedule.py가 collect_round_ends()로
  공시를 모아 처리한다. 이 파일을 직접 실행하면 보고서만 출력한다.
"""

import argparse
import collections
import re
import sys
from datetime import date, timedelta

import kind_client as kc
from krx_calendar import classify_record, next_biz

sys.stdout.reconfigure(encoding="utf-8")

REPORT_NM = "ETF이익금분배 수익자 확정"
TITLE_RX = r"설정/환매"
WD = "월화수목금토일"

# 패턴에 안 맞는데 이 이상 종목이 걸린 회차는 '확인필요'로 따로 보여준다.
BIG = 40


def calendar_records(path: str):
    """index.html의 CONFIRMED_SCHEDULE에서 기준일 날짜를 뽑는다. 실패하면 None."""
    try:
        with open(path, encoding="utf-8") as f:
            html = f.read()
    except OSError:
        return None
    m = re.search(r"const CONFIRMED_SCHEDULE\s*=\s*\[(.*?)\];", html, re.S)
    if not m:
        return None
    return set(re.findall(r"date:'(\d{4}-\d\d-\d\d)',\s*type:'record'", m.group(1)))


def fmt(d: date) -> str:
    return f"{d.isoformat()}({WD[d.weekday()]})"


def collect_round_ends(frm: str, to: str):
    """설정/환매 공시에서 {중지기간 종료일: 등장 횟수}, 공시 건수, 조회 실패 건수를 모은다.

    한 공시 문서에 여러 회차가 섞여 있고 비정기 상품은 자기만의 일정을 갖는다.
    여러 운용사가 같은 회차를 각각 공시하고, 같은 회차면 종료일이 같으므로 종료일로 묶는다.
    """
    rows = kc.search_disclosures(REPORT_NM, frm, to, title_filter=TITLE_RX)
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
    by_end = collections.defaultdict(int)
    for (st, en), n in periods.items():
        by_end[en] += n
    return dict(by_end), len(rows), failed


def main():
    ap = argparse.ArgumentParser(description="KIND 분배 일정 파악")
    ap.add_argument("--days", type=int, default=30, help="오늘 기준 최근 N일 (기본 30)")
    ap.add_argument("--from", dest="frm", help="YYYY-MM-DD")
    ap.add_argument("--to", dest="to", help="YYYY-MM-DD")
    ap.add_argument("--calendar", default="index.html",
                    help="CONFIRMED_SCHEDULE을 읽어 이미 반영된 회차를 표시할 파일")
    args = ap.parse_args()

    today = date.today()
    frm = args.frm or (today - timedelta(days=args.days)).isoformat()
    to = args.to or today.isoformat()

    print("=" * 60)
    print(f"📅 분배 일정 공시 검색: {frm} ~ {to}")
    print("=" * 60)

    by_end, n_rows, failed = collect_round_ends(frm, to)
    if not n_rows:
        print("검색 결과가 없습니다.")
        return
    print(f"공시 {n_rows}건 — 본문에서 중지기간 추출 완료\n")
    if not by_end:
        print("중지기간을 찾지 못했습니다.")
        return

    # 정규/비정기 판정은 종목수가 아니라 기준일 패턴으로 한다.
    # 종목수는 "몇 개 운용사가 공시했나"일 뿐이라 회차 성격의 신호가 아니고,
    # 실측에서 양방향으로 틀렸다.
    #   - 거짓 음성: 첫 공시 한 건만 올라온 시점에는 정규인데도 적게 잡힌다
    #   - 거짓 양성: 2026-08-03 기준일 회차는 22종목이지만 15일도 말일도 아닌 비정기
    # 기준일은 첫 공시나 백 번째 공시나 같은 값이므로 한 건만 있어도 판정된다.

    print(f"{'회차':<10}{'최종매수일':<18}{'배당락일':<18}{'기준일':<18}{'종목수':>6}  상태")
    print("-" * 92)

    results = []
    for en in sorted(by_end):
        cnt = by_end[en]
        last_buy = date.fromisoformat(en)
        ex = next_biz(last_buy)
        rec = next_biz(ex)
        kind = classify_record(rec)
        timing = kind or ("확인필요" if cnt >= BIG else "비정기")
        state = "지난 회차" if last_buy < today else ("오늘 마감" if last_buy == today else "예정")
        if kind is None:
            state += " · 기준일이 15일/말일 아님"
        print(f"{timing:<10}{fmt(last_buy):<18}{fmt(ex):<18}{fmt(rec):<18}{cnt:>6}  {state}")
        results.append((timing, last_buy, ex, rec, state, kind is not None, cnt))

    upcoming = [r for r in results if r[1] >= today and r[5]]
    review = [r for r in results if r[1] >= today and not r[5] and r[6] >= BIG]

    cal = calendar_records(args.calendar)
    if cal is None:
        print(f"\n⚠️ {args.calendar}에서 CONFIRMED_SCHEDULE을 읽지 못했습니다 — 전부 미반영으로 간주합니다.")
        cal = set()
    pending = [r for r in upcoming if r[3].isoformat() not in cal]

    if upcoming:
        print("\n" + "=" * 60)
        print("📌 다가오는 회차 — index.html CONFIRMED_SCHEDULE 에 넣을 형태")
        print("=" * 60)
        for timing, lb, ex, rec, _s, _m, cnt in upcoming:
            mark = "" if rec.isoformat() not in cal else "   ← 달력 반영 완료"
            print(f"  // {timing} 회차 ({cnt}종목){mark}")
            print(f"  {{date:'{lb}', type:'buy',    label:'최종매수',     ex:'{ex}'}},")
            print(f"  {{date:'{ex}', type:'ex',     label:'배당락',       ex:'{ex}'}},")
            print(f"  {{date:'{rec}', type:'record', label:'기준일({timing})', ex:'{ex}'}},")
        print("\n※ 월중·월말은 독립 회차이므로 해당 회차 3줄만 교체하고 나머지는 남겨둘 것.")
        print("※ 배당락일·기준일은 한국거래소 휴장일을 반영한 계산값이다.")
        print("※ 종목수는 지금까지 공시한 운용사 기준이라 회차가 진행되며 늘어난다.")
        print("   날짜는 운용사끼리 공유하므로 종목수와 무관하게 확정값이다.")

    if review:
        print("\n" + "=" * 60)
        print("⚠️ 확인필요 — 규모는 큰데 기준일이 15일/말일에 안 붙는 회차")
        print("=" * 60)
        for timing, lb, ex, rec, _s, _m, cnt in review:
            print(f"  최종매수 {fmt(lb)} → 기준일 {fmt(rec)} ({cnt}종목)")
        print("\n라이브러리가 모르는 임시공휴일 때문에 밀린 정규 회차일 수도, 비정기일 수도 있습니다.")

    if failed:
        print(f"\n⚠️ 문서 조회 실패 {failed}건")

    if pending:
        print(f"\n📅 달력 미반영 정규 회차 {len(pending)}개 — auto_schedule.py가 최종매수일 하루 전에 반영합니다")


if __name__ == "__main__":
    main()
