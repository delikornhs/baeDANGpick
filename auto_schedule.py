"""
분배 일정 자동 반영 — 최종매수일 하루 전(영업일)에 달력을 갱신하고, 반영되면 일정 뉴스레터를 보낸다.

  python -X utf8 auto_schedule.py                         # 점검만 (무엇을 할지 출력)
  python -X utf8 auto_schedule.py --today 2026-10-27      # 특정 날짜 기준으로 점검
  python -X utf8 auto_schedule.py --live                  # 실제 반영·발송 (GitHub Actions 안에서만)

■ 언제 무엇을 하나
  회차 날짜(최종매수 L · 배당락 X · 기준일 R)는 krx_calendar 규칙으로 계산한다.
  - 달력 반영:  L의 직전 영업일 ~ R  사이 실행에서, 달력에 없으면 넣는다
  - 일정 뉴스레터: L의 직전 영업일 ~ L 당일 장 시작(09시) 전 사이 실행에서, 아직 안 보냈으면 보낸다
    장이 열린 뒤에는 "오늘까지 매수" 안내가 의미 없으므로 보내지 않고 사람에게 알린다
  워크플로는 평일 08:00·18:30·20:30에 돈다. 하루 전 08:00에 처리되고, 나머지는 예약 실행이
  누락됐을 때를 위한 재시도다. 모든 단계가 '이미 했으면 건너뜀'이라 여러 번 돌아도 안전하다.

■ 관문 (하나라도 걸리면 반영·발송하지 않는다)
  1. 계산한 최종매수일이 KIND 공시의 실측 최종매수일(설정/환매 중지기간 종료일)과 일치해야 한다.
     라이브러리가 모르는 임시공휴일이 생기면 여기서 걸린다.
     공시가 아직 충분히 안 모였으면(5건 미만) 다음 실행에 다시 본다.
  2. 달력 편집 결과가 예상 형태(회차당 3줄, 월중·월말 각 1회차)여야 한다.
  3. 달력 push가 성공해야 뉴스레터를 보낸다.
  4. 같은 회차 뉴스레터가 archive.json에 있으면 보내지 않는다.
"""

import argparse
import re
import sys
import time
from datetime import date, timedelta

import requests

from auto_common import (archive_ids, commit_and_push, merge_archive_entry, archive_entry,
                         now_kst, resolve_live, send_newsletter, write_report)
from krx_calendar import holiday_name, prev_biz, rule_round

sys.stdout.reconfigure(encoding="utf-8")

INDEX = "index.html"
SITE = "https://baedangetf.com/"
MIN_CONFIRM = 5          # 이 이상 종목의 중지기간 종료일이 L과 같아야 실측 확인으로 본다
MARKET_OPEN_HOUR = 9
WD = "월화수목금토일"

ENTRY_RX = re.compile(
    r"\{date:'(\d{4}-\d\d-\d\d)',\s*type:'(\w+)',\s*label:'([^']*)',\s*ex:'(\d{4}-\d\d-\d\d)'\},?")
BLOCK_RX = re.compile(r"(const CONFIRMED_SCHEDULE\s*=\s*\[\n)(.*?)(\n\];)", re.S)


def fmt(d: date) -> str:
    return f"{d.isoformat()}({WD[d.weekday()]})"


def months_from(d: date, n: int):
    y, m = d.year, d.month
    for _ in range(n):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


# ── 달력(CONFIRMED_SCHEDULE) ─────────────────────────────────

def parse_calendar(html: str):
    """CONFIRMED_SCHEDULE 블록을 [(줄, 항목|None)] 로 나눈다. 예상 밖 줄이 있으면 None."""
    m = BLOCK_RX.search(html)
    if not m:
        return None
    lines = []
    for line in m.group(2).split("\n"):
        s = line.strip()
        e = ENTRY_RX.search(line)
        if e:
            lines.append((line, e.groups()))
        elif s == "" or s.startswith("//"):
            lines.append((line, None))
        else:
            return None
    return m, lines


def round_lines(timing, L, X, R):
    return [
        f"  {{date:'{L}', type:'buy',    label:'최종매수',     ex:'{X}'}},",
        f"  {{date:'{X}', type:'ex',     label:'배당락',       ex:'{X}'}},",
        f"  {{date:'{R}', type:'record', label:'기준일({timing})', ex:'{X}'}},",
    ]


def group_timing(entries) -> str:
    for _d, typ, label, _x in entries:
        if typ == "record":
            return "월중" if "월중" in label else ("월말" if "월말" in label else "")
    return ""


def calendar_has(html: str, timing, L, X, R) -> bool:
    parsed = parse_calendar(html)
    if not parsed:
        return False
    want = {(str(L), "buy", str(X)), (str(X), "ex", str(X)), (str(R), "record", str(X))}
    got = {(e[0], e[1], e[3]) for _line, e in parsed[1] if e}
    return want <= got


def update_calendar(html: str, timing, L, X, R):
    """해당 timing 회차 3줄만 교체(없으면 추가)한 html. 형태가 예상과 다르면 예외."""
    parsed = parse_calendar(html)
    if not parsed:
        raise ValueError("CONFIRMED_SCHEDULE 블록을 해석할 수 없습니다 (예상 밖 형태)")
    m, lines = parsed

    # 같은 배당락일(ex)을 공유하는 3줄이 한 회차다. 처음 나온 순서를 유지한다.
    groups, order = {}, []
    for line, e in lines:
        if e:
            groups.setdefault(e[3], []).append((line, e))
            if e[3] not in order:
                order.append(e[3])
    new_lines, replaced = [], False
    for line, e in lines:
        if not e:
            new_lines.append(line)
    for ex in order:
        ents = [e for _l, e in groups[ex]]
        if group_timing(ents) == timing:
            if not replaced:
                new_lines += round_lines(timing, L, X, R)
                replaced = True
            continue                         # 같은 timing의 옛 회차는 버린다
        new_lines += [l for l, _e in groups[ex]]
    if not replaced:
        new_lines += round_lines(timing, L, X, R)

    body = "\n".join(new_lines)
    out = html[:m.start(2)] + body + html[m.end(2):]

    # 관문 2: 결과 형태 점검
    chk = parse_calendar(out)
    if not chk:
        raise ValueError("편집 결과를 다시 해석할 수 없습니다")
    ents = [e for _l, e in chk[1] if e]
    by_ex = {}
    for e in ents:
        by_ex.setdefault(e[3], []).append(e)
    timings = [group_timing(g) for g in by_ex.values()]
    if any(len(g) != 3 for g in by_ex.values()) or len(timings) != len(set(timings)) or "" in timings:
        raise ValueError(f"편집 결과 형태 이상: 회차별 줄 수 {[len(g) for g in by_ex.values()]}, timing {timings}")
    if not calendar_has(out, timing, L, X, R):
        raise ValueError("편집 결과에 새 회차가 없습니다")
    return out


def wait_site(L, timeout=300) -> bool:
    """배포가 끝나 사이트에 새 최종매수일이 보일 때까지 기다린다."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(SITE, params={"t": int(time.time())}, timeout=20,
                             headers={"Cache-Control": "no-cache"})
            if f"date:'{L}'" in r.text:
                return True
        except requests.RequestException:
            pass
        time.sleep(30)
    return False


# ── 메인 ────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="분배 일정 자동 반영")
    ap.add_argument("--live", action="store_true", help="실제 반영·발송 (GitHub Actions 안에서만)")
    ap.add_argument("--today", help="YYYY-MM-DD — 이 날짜 기준으로 판단 (점검용)")
    ap.add_argument("--hour", type=int, help="KST 시각(0~23) — 점검용")
    args = ap.parse_args()

    live = resolve_live(args.live)
    now = now_kst()
    today = date.fromisoformat(args.today) if args.today else now.date()
    hour = args.hour if args.hour is not None else now.hour
    mode = "실전" if live else "점검(dry-run)"
    print(f"📅 분배 일정 자동 반영 — {fmt(today)} {hour:02d}시 KST · {mode}\n")

    rounds = []
    for y, m in months_from(today - timedelta(days=20), 3):
        for timing in ("월중", "월말"):
            L, X, R = rule_round(timing, y, m)
            rounds.append(dict(timing=timing, y=y, m=m, L=L, X=X, R=R, act=prev_biz(L)))
    rounds.sort(key=lambda r: r["L"])

    due = [r for r in rounds if r["act"] <= today <= r["R"]]
    if not due:
        nxt = next((r for r in rounds if r["act"] > today), None)
        msg = (f"다음 회차: {nxt['m']}월 {nxt['timing']} — 최종매수 {fmt(nxt['L'])}, "
               f"반영 예정 {fmt(nxt['act'])}") if nxt else "예정된 회차 없음"
        print(f"할 일 없음. {msg}")
        write_report("auto_schedule", "nothing", "", [msg])
        return

    try:
        with open(INDEX, encoding="utf-8") as f:
            html = f.read()
    except OSError as e:
        write_report("auto_schedule", "held", "📅 일정 자동 반영 실패 — index.html 읽기 오류", [str(e)])
        return
    sent_ids = archive_ids()

    statuses, report = [], []
    by_end = None                                   # KIND 공시 — 필요할 때 한 번만 조회

    for r in due:
        timing, L, X, R, act = r["timing"], r["L"], r["X"], r["R"], r["act"]
        slug = "mid" if timing == "월중" else "end"
        aid = f"{r['y']}-{r['m']:02d}-{slug}-schedule"
        head = f"{r['m']}월 {timing} — 최종매수 {fmt(L)} · 배당락 {fmt(X)} · 기준일 {fmt(R)}"
        print(f"▶ {head}")
        report += [f"### {head}", ""]
        # 사이에 낀 휴장일을 보고서에 남긴다 (계산 근거)
        gap = [act + timedelta(days=i) for i in range((R - act).days + 1)]
        hol = [f"{fmt(d)} {holiday_name(d)}" for d in gap if holiday_name(d)]
        if hol:
            report.append(f"- 사이의 휴장일: {', '.join(hol)}")

        in_cal = calendar_has(html, timing, L, X, R)
        sent = aid in sent_ids
        nl_window = act <= today < L or (today == L and hour < MARKET_OPEN_HOUR)
        print(f"   달력 반영 {'O' if in_cal else 'X'} · 뉴스레터 발송 {'O' if sent else 'X'} · "
              f"발송 시간대 {'안' if nl_window else '밖'}")

        if in_cal and sent:
            print("   이미 처리됨")
            report += ["- 이미 처리됨 (달력 반영·뉴스레터 발송 완료)", ""]
            statuses.append(("nothing", ""))
            continue

        # 관문 1: KIND 실측 최종매수일과 대조
        if not in_cal:
            if by_end is None:
                from kind_schedule import collect_round_ends
                frm = (today - timedelta(days=40)).isoformat()
                try:
                    by_end, n_rows, failed = collect_round_ends(frm, today.isoformat())
                    print(f"   KIND 설정/환매 공시 {n_rows}건 조회 (문서 실패 {failed})")
                except Exception as e:
                    by_end = {}
                    print(f"   ⚠️ KIND 조회 실패: {e}")
            cnt = by_end.get(L.isoformat(), 0)
            near = sorted((k, v) for k, v in by_end.items()
                          if abs((date.fromisoformat(k) - L).days) <= 6)
            report.append(f"- KIND 실측: 최종매수일 {L} 로 공시된 종목 {cnt}개"
                          + (f" (근처 종료일: {', '.join(f'{k} {v}개' for k, v in near)})" if near else ""))
            if cnt < MIN_CONFIRM:
                last_chance = today >= L
                if not last_chance:
                    print(f"   ⏳ 실측 확인 부족({cnt}개 < {MIN_CONFIRM}) — 다음 실행에 다시 확인")
                    report += [f"- ⏳ 실측 확인 부족 — 다음 실행에 다시 확인합니다", ""]
                    statuses.append(("waiting", ""))
                else:
                    msg = ("계산한 최종매수일이 KIND 공시로 확인되지 않아 반영하지 않았습니다. "
                           "임시공휴일 등으로 일정이 달라졌을 수 있습니다.")
                    print(f"   ⛔ {msg}")
                    report += [f"- ⛔ {msg}", ""]
                    statuses.append(("held", f"📅 {r['m']}월 {timing} 일정 자동 반영 보류 — 공시 불일치 [{aid}]"))
                continue

            # 달력 편집 → push
            try:
                new_html = update_calendar(html, timing, L, X, R)
            except ValueError as e:
                report += [f"- ⛔ 달력 편집 중단: {e}", ""]
                statuses.append(("held", f"📅 {r['m']}월 {timing} 일정 자동 반영 실패 — 달력 형태 [{aid}]"))
                continue
            msg = f"chore: {r['m']}월 {timing} 배당 일정 업데이트 (자동 — 최종매수 {L})"
            if not live:
                print(f"   [점검] 달력 반영 예정: {msg}")
                report.append(f"- [점검] 달력에 반영할 예정")
            else:
                def reapply():
                    with open(INDEX, encoding="utf-8") as f:
                        cur = f.read()
                    if calendar_has(cur, timing, L, X, R):
                        return False
                    with open(INDEX, "w", encoding="utf-8", newline="") as f:
                        f.write(update_calendar(cur, timing, L, X, R))
                    return True
                try:
                    with open(INDEX, "w", encoding="utf-8", newline="") as f:
                        f.write(new_html)
                    res = commit_and_push([INDEX], msg, reapply)
                except Exception as e:
                    report += [f"- ⛔ 달력 push 실패: {e}", ""]
                    statuses.append(("held", f"📅 {r['m']}월 {timing} 일정 자동 반영 실패 — push [{aid}]"))
                    continue
                print(f"   ✅ 달력 반영 ({res})")
                report.append(f"- ✅ 달력 반영 ({res})")
                with open(INDEX, encoding="utf-8") as f:
                    html = f.read()
                ok = wait_site(L)
                report.append(f"- 사이트 배포 확인: {'완료' if ok else '5분 내 미확인 (배포 지연 가능)'}")
            in_cal = True
        else:
            report.append("- 달력: 이미 반영돼 있음 (규칙 계산과 일치)")

        # 뉴스레터
        if sent:
            report += ["- 뉴스레터: 이미 발송됨", ""]
            statuses.append(("done", ""))
            continue
        if not nl_window:
            # due 범위 안에서 시간대 밖이면 '최종매수일 장 시작 이후'뿐이다
            msg = ("일정 뉴스레터를 보내지 못한 채 발송 시간대(최종매수일 장 시작 전)가 지났습니다. "
                   "지금 보내면 '오늘까지 매수' 안내가 틀리므로 자동으로 보내지 않았습니다.")
            print(f"   ⚠️ {msg}")
            report += [f"- ⚠️ {msg}", ""]
            statuses.append(("held", f"📅 {r['m']}월 {timing} 일정 뉴스레터 미발송 — 시간대 지남 [{aid}]"))
            continue
        if f"{today:%Y-%m}" != f"{r['y']}-{r['m']:02d}":
            report += ["- ⛔ 뉴스레터: 회차 월과 발송 월이 달라 아카이브 기록이 어긋나므로 보내지 않았습니다", ""]
            statuses.append(("held", f"📅 {r['m']}월 {timing} 일정 뉴스레터 보류 — 월 불일치 [{aid}]"))
            continue
        nl_args = ["--type", "schedule", "--timing", timing,
                   "--last-buy", str(L), "--ex-date", str(X), "--record", str(R)]
        if not live:
            print(f"   [점검] 일정 뉴스레터 발송 예정: {' '.join(nl_args)}")
            report += [f"- [점검] 일정 뉴스레터 발송 예정 ({aid})", ""]
            statuses.append(("done", f"📅 [점검] {r['m']}월 {timing} 일정 반영·발송 예정"))
            continue
        code, _out = send_newsletter(nl_args)
        if code == 1:
            report += ["- ⛔ 뉴스레터 발송 실패 — 발송되지 않았습니다(다음 실행에 재시도)", ""]
            statuses.append(("held", f"📅 {r['m']}월 {timing} 일정 뉴스레터 발송 실패 [{aid}]"))
            continue
        entry = archive_entry(aid)
        try:
            commit_and_push(["data/output/newsletter/archive.json"],
                            f"chore: newsletter archive update (schedule/{timing}, 자동)",
                            lambda: merge_archive_entry(entry) if entry else False)
        except Exception as e:
            report.append(f"- ⚠️ 아카이브 커밋 실패: {e} — 중복 발송 위험이 있으니 확인 필요")
            statuses.append(("held", f"📅 {r['m']}월 {timing} 일정 뉴스레터 아카이브 커밋 실패 [{aid}]"))
            continue
        if code == 2:
            report += ["- ⚠️ 뉴스레터 결과 불명 — 중복 방지를 위해 '미확인'으로 기록했습니다. 수신 여부 확인 필요", ""]
            statuses.append(("held", f"📅 {r['m']}월 {timing} 일정 뉴스레터 결과 미확인 [{aid}]"))
        else:
            sent_n = (entry or {}).get("sent")
            report += [f"- ✅ 일정 뉴스레터 발송 완료" + (f" ({sent_n}명)" if sent_n is not None else ""), ""]
            statuses.append(("done", f"📅 {r['m']}월 {timing} 일정 달력 반영·뉴스레터 발송 완료 [{aid}]"))

    rank = {"held": 3, "done": 2, "waiting": 1, "nothing": 0}
    status, title = max(statuses, key=lambda s: rank[s[0]]) if statuses else ("nothing", "")
    write_report("auto_schedule", status, title, report)


if __name__ == "__main__":
    main()
