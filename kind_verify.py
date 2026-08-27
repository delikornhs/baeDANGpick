"""
프로세서 실행 결과(latest.json)가 사이트에 올려도 되는 상태인지 검증한다.

  python -X utf8 kind_verify.py          # 통과 0 / 실패 1 로 종료

GitHub Actions가 자동 반영 전에 호출한다. 하나라도 실패하면 커밋하지 않는다.

■ CLAUDE.md의 수동 검증과 다른 점
  수동 검증은 사람이 '이번엔 월말, 2026-06' 처럼 대상을 알려주는 전제였다.
  자동 실행에는 그 입력이 없으므로, 대상을 몰라도 성립하는 불변식만 확인한다.
  또 직전 커밋본과 비교해 '조용한 손실'(종목이 대량으로 사라지는 경우)을 잡는다.
"""

import json
import subprocess
import sys
from datetime import date, datetime

sys.stdout.reconfigure(encoding="utf-8")

LATEST = "data/output/latest.json"
MIN_CURRENT = 50          # current=True 최소 종목 수
MAX_DROP_RATIO = 0.7      # 직전 대비 이 비율 미만으로 줄면 실패
STALE_DAYS = 45           # 최신 기준일이 오늘에서 이만큼 이상 떨어져 있으면 의심


def load_previous():
    """직전 커밋의 latest.json (없으면 None)"""
    try:
        out = subprocess.run(["git", "show", f"HEAD:{LATEST}"],
                             capture_output=True, timeout=60)
        if out.returncode != 0:
            return None
        return json.loads(out.stdout.decode("utf-8"))
    except Exception:
        return None


def main():
    with open(LATEST, encoding="utf-8") as f:
        data = json.load(f)

    results = []   # (통과여부, 메시지)

    def check(ok, msg):
        results.append((ok, msg))

    current = [x for x in data if x.get("current")]

    # 1) current 종목 수
    check(len(current) >= MIN_CURRENT,
          f"current=True {len(current)}개 (최소 {MIN_CURRENT})")

    # 2) 분배금이 0 이하인 항목이 없어야 함
    bad_dist = [x for x in current if not (x.get("dist", 0) > 0)]
    check(not bad_dist,
          f"분배금 0 이하 {len(bad_dist)}개" +
          (f" — 예: {bad_dist[0]['name'][:24]}" if bad_dist else ""))

    # 3) 지급일은 기준일보다 나중이어야 함
    bad_pay = [x for x in current
               if x.get("pay_date") and x.get("ex_date") and x["pay_date"] <= x["ex_date"]]
    check(not bad_pay,
          f"지급일<=기준일 {len(bad_pay)}개" +
          (f" — 예: {bad_pay[0]['name'][:24]} {bad_pay[0]['ex_date']}→{bad_pay[0]['pay_date']}"
           if bad_pay else ""))

    # 4) 최신 기준일이 최근이어야 함 (이전 달 데이터가 그대로 남은 경우 탐지)
    ex_dates = sorted({x["ex_date"] for x in current if x.get("ex_date")})
    if ex_dates:
        newest = ex_dates[-1]
        gap = abs((date.today() - datetime.strptime(newest, "%Y-%m-%d").date()).days)
        check(gap <= STALE_DAYS, f"최신 기준일 {newest} (오늘과 {gap}일 차이)")
    else:
        check(False, "기준일이 있는 current 항목 없음")

    # 5) 분배율이 상식 범위인지 (계산 오류 탐지)
    bad_rate = [x for x in current if x.get("rate") is not None and not (0 <= x["rate"] < 50)]
    check(not bad_rate,
          f"분배율 이상치 {len(bad_rate)}개" +
          (f" — 예: {bad_rate[0]['name'][:24]} {bad_rate[0].get('rate')}%" if bad_rate else ""))

    # 6) 직전 커밋 대비 '조용한 손실'이 없는지
    #    ⚠️ current 총계를 그대로 비교하면 안 된다. 월말 회차 종목 수는 결산이 몰리는 달
    #       (4·7·12·1월) 300~500개, 평월 120~135개로 정상적으로 3~4배 오르내린다.
    #       총계 비교는 회차가 교체되는 시점 — 프로세서가 도는 바로 그때 — 마다 울린다.
    #    → 양쪽에 공통으로 있는 기준일만 비교한다. 같은 회차라면 종목이 줄 이유가 없으므로
    #       원래 잡으려던 손실은 그대로 걸리고, 회차 교체는 오탐하지 않는다.
    #
    #    2026-08-27 거짓 경보: 직전 448개(월말 7/31 399 + 월중 8/14 49) 대비
    #    현재 187개(월말 8/31 135 + 월중 8/14 49 + 비정기 3)로 42%가 나와 반영이 막혔다.
    #    공시 원본 138건 = 135 + 3 으로 정확히 일치해 실제 손실은 없었다.
    prev = load_previous()
    if prev is None:
        check(True, "직전 latest.json 없음 — 비교 생략")
    else:
        def count_by_ex(items):
            c = {}
            for x in items:
                if x.get("current") and x.get("ex_date"):
                    c[x["ex_date"]] = c.get(x["ex_date"], 0) + 1
            return c

        prev_by_ex = count_by_ex(prev)
        cur_by_ex  = count_by_ex(data)
        shared = sorted(set(prev_by_ex) & set(cur_by_ex))
        if not shared:
            check(True, "공통 기준일 없음(회차 전면 교체) — 비교 생략 "
                        f"[직전 {','.join(sorted(prev_by_ex)) or '없음'}"
                        f" → 현재 {','.join(sorted(cur_by_ex)) or '없음'}]")
        else:
            drops = [(ex, prev_by_ex[ex], cur_by_ex[ex]) for ex in shared
                     if cur_by_ex[ex] < prev_by_ex[ex] * MAX_DROP_RATIO]
            check(not drops,
                  f"공통 기준일 {len(shared)}개 종목 수 유지 "
                  f"({', '.join(f'{ex} {cur_by_ex[ex]}개' for ex in shared)})"
                  if not drops else
                  "급감: " + ", ".join(f"{ex} {p}→{c}개" for ex, p, c in drops))

    # ── 출력 ──
    print("=" * 60)
    print("🔍 데이터 검증")
    print("=" * 60)
    for ok, msg in results:
        print(f"  {'✅' if ok else '❌'} {msg}")

    # 참고 정보 (사람이 보고 판단할 수 있도록)
    by_timing = {}
    for x in current:
        t = x.get("timing") or "(비정기)"
        by_timing[t] = by_timing.get(t, 0) + 1
    print("\n📊 현재 반영 대상")
    for t, n in sorted(by_timing.items()):
        print(f"   {t}: {n}개")
    if ex_dates:
        print(f"   기준일: {', '.join(ex_dates[-4:])}")

    monthly = [x for x in current if x.get("freq") in ("월배당", "월배당추정")]
    top = sorted(monthly, key=lambda x: x.get("rate", 0), reverse=True)[:5]
    if top:
        print("\n📈 분배율 TOP 5")
        for i, x in enumerate(top, 1):
            print(f"   {i}. {x['name'][:32]:<34} {x.get('rate')}%  {x.get('dist')}원")

    failed = [m for ok, m in results if not ok]
    print()
    if failed:
        print(f"❌ 검증 실패 {len(failed)}건 — 사이트 반영을 중단합니다.")
        return 1
    print("✅ 검증 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
