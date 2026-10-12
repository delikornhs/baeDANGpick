"""
분배금 데이터 뉴스레터 자동 발송 — 이번 달 회차 데이터가 사이트에 반영돼 있고 아직 안 보냈으면 보낸다.

  python -X utf8 auto_data_newsletter.py                      # 점검만 (관문 결과 출력)
  python -X utf8 auto_data_newsletter.py --today 2026-10-13   # 특정 날짜 기준 점검
  python -X utf8 auto_data_newsletter.py --live               # 실제 발송 (GitHub Actions 안에서만)

kind-watch.yml 이 공시를 수집·검증해 push한 뒤 실행한다. 판단 기준은 저장소의 데이터와
newsletter/archive.json 뿐이라, 여러 번 돌아도 회차당 한 번만 나간다.

■ 관문 (하나라도 걸리면 보내지 않고 사람에게 알린다)
  1. 회차 — 해당 timing의 current 항목이 모두 같은 기준일이고, 그 기준일이 이번 달이며,
           기준일로부터 7일이 지나지 않았다. (지난달 데이터가 그대로 나가는 것을 막는다 —
           2026-06-26에 history.json만 먼저 push된 상태로 발송돼 5월 데이터가 나간 적이 있다)
  2. 지급일 — 모든 항목의 지급일이 기준일보다 뒤다.
  3. 종목 수 — 월배당 상품만 센다. ① history.json의 이번 회차가 같은 timing 최근 6회차 중앙값의
           70% 이상이고 ② latest.json에서 이번 회차로 잡힌 수가 history.json의 90% 이상이어야 한다.
           ②는 뉴스레터를 만드는 latest.json 쪽 누락을 잡는다(history만 보면 못 잡는다).
           월배당만 세는 이유: 결산월(4·7·12·1월)에는 분기·연배당 상품이 같은 기준일에 몰려 전체 수가
           300~500개로 튀지만, 월배당은 매달 121~138개(월말)로 안정적이다. 2026-09 두 회차 모두
           두 파일의 월배당 수가 정확히 일치했다(50/50, 136/136).
           (예전 수동 기준 '50개 이상'은 월중(보통 46~51개)에서 정상인데도 걸렸다)
  4. 분배율 — 발송할 상위 15개의 분배율을 저장된 원시 종가로 다시 계산해 1% 안에서 일치한다.
           2026-09-29 발견한 수정주가 오류(분배율이 3.00% → 3.10%로 부풀려짐)는 여기서 걸린다.
  5. 원시 종가 — 데일리 실행의 일관성 검사(price_integrity.json)에서 발송 대상 종목이 걸리지 않았다.
           네이버가 가격 방식을 바꾸거나 분배 기록이 빠지면 과거 종가가 달라지는데, 그 신호다.
  6. 중복 — 같은 회차가 archive.json에 없다.
"""

import argparse
import json
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

from auto_common import (archive_entry, archive_ids, commit_and_push, merge_archive_entry,
                         now_kst, resolve_live, send_newsletter, write_report)
from krx_calendar import classify_record

sys.stdout.reconfigure(encoding="utf-8")

LATEST = Path("data/output/latest.json")
HISTORY = Path("data/output/history.json")
PRICE_DIR = Path("data/output/price_history")
FORMAT_FILE = PRICE_DIR / "_format.json"
INTEGRITY_FILE = Path("data/output/price_integrity.json")
TOP_N = 15                     # trigger_newsletter.py 와 같은 값
STALE_DAYS = 7
RATE_TOL = 0.01                # 분배율 상대 오차 허용치


def newsletter_targets(latest, timing):
    """trigger_newsletter.py 가 실제로 보내는 목록과 같은 방식으로 고른다."""
    cur = [e for e in latest
           if e.get("current") and e.get("freq") in ("월배당", "월배당추정") and e.get("timing") == timing]
    cur.sort(key=lambda x: float(x.get("rate", 0)), reverse=True)
    return cur[:TOP_N]


MONTHLY = ("월배당", "월배당추정")


def monthly_round_counts(history, latest):
    """{기준일: 월배당 상품 수}. 주기는 latest.json 기준."""
    freq = {e["isin"]: e.get("freq") for e in latest}
    c = {}
    for isin, recs in history.items():
        if freq.get(isin) not in MONTHLY:
            continue
        for ex in recs:
            c[ex] = c.get(ex, 0) + 1
    return c


def check_round(latest, timing, today):
    items = [e for e in latest if e.get("current") and e.get("timing") == timing]
    if not items:
        return None, "current 항목 없음"
    exs = {e.get("ex_date") for e in items}
    if len(exs) != 1:
        return None, f"이상: 기준일이 여러 개 섞여 있음 {sorted(exs)}"
    return date.fromisoformat(exs.pop()), ""


def main():
    ap = argparse.ArgumentParser(description="분배금 데이터 뉴스레터 자동 발송")
    ap.add_argument("--live", action="store_true", help="실제 발송 (GitHub Actions 안에서만)")
    ap.add_argument("--today", help="YYYY-MM-DD — 이 날짜 기준으로 판단 (점검용)")
    args = ap.parse_args()

    live = resolve_live(args.live)
    today = date.fromisoformat(args.today) if args.today else now_kst().date()
    print(f"📨 데이터 뉴스레터 자동 발송 — {today} · {'실전' if live else '점검(dry-run)'}\n")

    with open(LATEST, encoding="utf-8") as f:
        latest = json.load(f)
    with open(HISTORY, encoding="utf-8") as f:
        history = json.load(f)
    counts = monthly_round_counts(history, latest)
    sent_ids = archive_ids()

    integrity = None
    if INTEGRITY_FILE.exists():
        with open(INTEGRITY_FILE, encoding="utf-8") as f:
            integrity = json.load(f)

    statuses, report = [], []
    for timing, slug in (("월중", "mid"), ("월말", "end")):
        rec, why = check_round(latest, timing, today)
        if why.startswith("이상"):
            # 정상이라면 생기지 않는 상태 — 조용히 넘기면 발송이 안 된 걸 아무도 모른다
            aid = f"{today:%Y-%m}-{slug}-data"
            print(f"▶ {timing}: ⛔ {why}")
            report += [f"### {today.month}월 {timing}", "", f"- ⛔ {why} — 발송하지 않았습니다", ""]
            statuses.append(("held", f"📨 {today.month}월 {timing} 데이터 뉴스레터 보류 — 기준일 혼재 [{aid}]"))
            continue
        if why:
            print(f"▶ {timing}: 대상 아님 — {why}")
            continue

        # 발송 기록은 회차의 달로 찾는다. 오늘 날짜로 찾으면 월이 바뀐 뒤 지난달 회차를
        # '안 보낸 것'으로 오해한다.
        aid = f"{rec:%Y-%m}-{slug}-data"
        if aid in sent_ids:
            print(f"▶ {timing} {rec}: 이미 발송됨 ({aid})")
            continue
        late = (today - rec).days
        if (rec.year, rec.month) != (today.year, today.month) or late > STALE_DAYS:
            if late > 31:
                print(f"▶ {timing} {rec}: 오래된 회차 — 대상 아님")
                continue
            # 공시 수집이 며칠 막혔다 풀린 경우 등. trigger_newsletter.py 는 '발송한 달'로
            # 뉴스레터 제목과 기록을 만들기 때문에 자동으로 보내면 월 표기가 틀어진다.
            msg = (f"{rec.month}월 {timing} 회차(기준일 {rec}) 데이터 뉴스레터가 아직 발송되지 않았는데 "
                   f"발송 시점을 놓쳤습니다(월이 바뀌었거나 기준일로부터 {STALE_DAYS}일 경과). "
                   "자동 발송하면 월 표기가 틀어질 수 있어 보내지 않았습니다.")
            print(f"▶ {timing} {rec}: ⛔ {msg}")
            report += [f"### {rec.month}월 {timing}", "", f"- ⛔ {msg}", ""]
            statuses.append(("held", f"📨 {rec.month}월 {timing} 데이터 뉴스레터 미발송 — 시점 지남 [{aid}]"))
            continue

        head = f"{today.month}월 {timing} (기준일 {rec})"
        print(f"▶ {head} — 발송 대상, 관문 점검")
        report += [f"### {head}", ""]
        fails, warns = [], []
        items = [e for e in latest if e.get("current") and e.get("timing") == timing]
        targets = newsletter_targets(latest, timing)

        # 관문 2: 지급일
        bad_pay = [e["name"] for e in items if not e.get("pay_date") or e["pay_date"] <= e["ex_date"]]
        if bad_pay:
            fails.append(f"지급일이 기준일 이전·같음·없음 {len(bad_pay)}개: {bad_pay[:3]}")
        report.append(f"- 지급일: {'❌' if bad_pay else '✅'} {items[0].get('pay_date')} > {rec}"
                      + (f" — 이상 {len(bad_pay)}개" if bad_pay else ""))

        # 관문 3: 종목 수 (월배당만)
        n_hist = counts.get(str(rec), 0)
        n_latest = len([e for e in items if e.get("freq") in MONTHLY])
        past = sorted((d, c) for d, c in counts.items()
                      if d < str(rec) and classify_record(date.fromisoformat(d)) == timing)
        recent = [c for _d, c in past[-6:]]
        base = statistics.median(recent) if recent else 0
        ok_n = (n_hist >= 0.7 * base and n_latest >= 0.9 * n_hist and len(targets) >= TOP_N)
        if not ok_n:
            fails.append(f"종목 수 이상: 이번 회차 {n_hist}개(최근 6회 중앙값 {base:g}), "
                         f"latest.json 반영 {n_latest}개, 발송 대상 {len(targets)}개")
        report.append(f"- 종목 수(월배당): {'✅' if ok_n else '❌'} 이번 회차 {n_hist}개 — 최근 6회차 중앙값 {base:g}, "
                      f"latest.json 반영 {n_latest}개")

        # 관문 4: 분배율 재계산
        if not FORMAT_FILE.exists():
            fails.append("price_history 가 원시 종가 형식이 아님(_format.json 없음)")
        bad_rate, checked = [], 0
        for e in targets:
            try:
                with open(PRICE_DIR / f"{e['code']}.json", encoding="utf-8") as f:
                    rows = json.load(f)
            except OSError:
                bad_rate.append(f"{e['name']}: 종가 이력 없음")
                continue
            prev = [p for d, p in rows if d < e.get("notice_date", "")]
            if not prev or not prev[-1]:
                bad_rate.append(f"{e['name']}: 공시 전일 종가 없음")
                continue
            expect = round(e["dist"] / prev[-1] * 100, 2)
            checked += 1
            if abs(e["rate"] - expect) > max(0.011, expect * RATE_TOL):
                bad_rate.append(f"{e['name']}: 표시 {e['rate']}% / 원시 종가 기준 {expect}%")
        if bad_rate:
            fails.append(f"분배율 불일치 {len(bad_rate)}개: {bad_rate[:3]}")
        report.append(f"- 분배율 재계산: {'❌' if bad_rate else '✅'} 상위 {checked}개 확인"
                      + (f" — 불일치 {len(bad_rate)}개" if bad_rate else ""))
        for b in bad_rate[:5]:
            report.append(f"  - {b}")

        # 관문 5: 원시 종가 일관성
        if integrity is None:
            warns.append("price_integrity.json 없음 — 데일리 실행이 아직 이 파일을 만들지 않았음")
            report.append("- 원시 종가 일관성: ⚠️ 검사 결과 파일 없음 (분배율 재계산으로 대신 확인)")
        else:
            hit = [m for m in integrity.get("mismatches", [])
                   if m["code"] in {e["code"] for e in targets}]
            if hit:
                fails.append(f"원시 종가가 바뀐 종목이 발송 대상에 {len(hit)}개: "
                             f"{[(m['name'], m['date'], m['gap_pct']) for m in hit[:3]]}")
            report.append(f"- 원시 종가 일관성: {'❌' if hit else '✅'} "
                          f"(검사 {integrity.get('checked_at')}, 전체 경고 {integrity.get('mismatch_count')}개, "
                          f"발송 대상 중 {len(hit)}개)")
            if not integrity.get("compared"):
                warns.append("마지막 일관성 검사가 비교 없이 끝남(원시 종가 변환 첫 실행)")

        report.append("")
        report.append("상위 5개: " + ", ".join(f"{e['name']} {e['rate']}%" for e in targets[:5]))
        for w in warns:
            report.append(f"- ⚠️ {w}")

        if fails:
            print("   ⛔ 관문 실패 — 발송하지 않음")
            for x in fails:
                print(f"     - {x}")
            report += ["", "**⛔ 관문에 걸려 발송하지 않았습니다.** 데이터를 확인한 뒤 Claude에게 "
                       "`\"데이터 뉴스레터 보내줘\"`라고 요청하세요."]
            statuses.append(("held", f"📨 {today.month}월 {timing} 데이터 뉴스레터 보류 — 관문 실패 [{aid}]"))
            continue

        print("   ✅ 관문 모두 통과")
        if not live:
            print(f"   [점검] 발송 예정: --type data --timing {timing}")
            report += ["", f"- [점검] 발송 예정 ({aid})"]
            statuses.append(("done", f"📨 [점검] {today.month}월 {timing} 데이터 뉴스레터 발송 예정"))
            continue

        code, _out = send_newsletter(["--type", "data", "--timing", timing])
        if code == 1:
            report += ["", "- ⛔ 발송 실패 — 발송되지 않았습니다(다음 실행에 재시도)"]
            statuses.append(("held", f"📨 {today.month}월 {timing} 데이터 뉴스레터 발송 실패 [{aid}]"))
            continue
        entry = archive_entry(aid)
        if not entry:
            report += ["", "- ⛔ 발송 후 아카이브 기록을 찾지 못함 — 수신 여부 확인 필요"]
            statuses.append(("held", f"📨 {today.month}월 {timing} 데이터 뉴스레터 기록 누락 [{aid}]"))
            continue
        try:
            commit_and_push(["data/output/newsletter/archive.json"],
                            f"chore: newsletter archive update (data/{timing}, 자동)",
                            lambda: merge_archive_entry(entry))
        except Exception as e:
            report += ["", f"- ⚠️ 아카이브 커밋 실패: {e} — 중복 발송 위험이 있으니 확인 필요"]
            statuses.append(("held", f"📨 {today.month}월 {timing} 데이터 뉴스레터 아카이브 커밋 실패 [{aid}]"))
            continue
        if code == 2:
            report += ["", "- ⚠️ 결과 불명 — 중복 방지를 위해 '미확인'으로 기록했습니다. 수신 여부 확인 필요"]
            statuses.append(("held", f"📨 {today.month}월 {timing} 데이터 뉴스레터 결과 미확인 [{aid}]"))
        else:
            report += ["", f"- ✅ 발송 완료 ({entry.get('sent')}명)"]
            statuses.append(("done", f"📨 {today.month}월 {timing} 데이터 뉴스레터 발송 완료 [{aid}]"))

    if not statuses:
        print("\n보낼 회차 없음")
    rank = {"held": 3, "done": 2, "waiting": 1, "nothing": 0}
    status, title = max(statuses, key=lambda s: rank[s[0]]) if statuses else ("nothing", "")
    write_report("auto_data_newsletter", status, title, report)


if __name__ == "__main__":
    main()
