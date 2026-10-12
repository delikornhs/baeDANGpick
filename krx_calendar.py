"""
한국거래소(KRX) 영업일과 정규 분배 회차 날짜 계산.

분배 일정(최종매수일·배당락일·기준일)은 영업일 기준이라 공휴일을 알아야 정확하다.
`holidays` 라이브러리의 XKRX(한국거래소) 휴장일을 쓴다 — 대체공휴일·임시공휴일·연말휴장일 포함.

■ 검증 (2026-10-12)
  - 2025-01-02 ~ 2026-10-08 평일 전수를 실제 거래 기록(KODEX 200 종가 이력)과 대조 → 불일치 0
    (2025-06-03 대선 임시공휴일, 2026-09-24~25 추석, 2025-12-31 연말휴장 포함)
  - 2025-08 ~ 2026-09 정규 분배 회차 35개의 기준일이 아래 규칙과 전부 일치

■ 정규 회차 규칙
  월중 기준일 = 그 달 15일, 휴장이면 직전 영업일
  월말 기준일 = 그 달 마지막 영업일
  배당락일    = 기준일 직전 영업일
  최종매수일  = 배당락일 직전 영업일

⚠️ 라이브러리가 모르는 임시공휴일이 갑자기 지정되면 계산이 하루 어긋난다.
   그래서 자동 반영은 이 계산을 KIND 공시의 실측 최종매수일과 대조해 일치할 때만 진행한다.
"""

from datetime import date, timedelta

import holidays

_CACHE = {}


def _krx(year: int):
    if year not in _CACHE:
        _CACHE[year] = holidays.financial_holidays("XKRX", years=year)
    return _CACHE[year]


def is_biz(d: date) -> bool:
    return d.weekday() < 5 and d not in _krx(d.year)


def holiday_name(d: date) -> str:
    return _krx(d.year).get(d, "")


def next_biz(d: date) -> date:
    d += timedelta(days=1)
    while not is_biz(d):
        d += timedelta(days=1)
    return d


def prev_biz(d: date) -> date:
    d -= timedelta(days=1)
    while not is_biz(d):
        d -= timedelta(days=1)
    return d


def on_or_before_biz(d: date) -> date:
    while not is_biz(d):
        d -= timedelta(days=1)
    return d


def mid_record_day(year: int, month: int) -> date:
    return on_or_before_biz(date(year, month, 15))


def eom_record_day(year: int, month: int) -> date:
    first_of_next = date(year + month // 12, month % 12 + 1, 1)
    return on_or_before_biz(first_of_next - timedelta(days=1))


def classify_record(rec: date):
    """기준일이 정규 회차 규칙에 맞으면 '월중'/'월말', 아니면 None."""
    if rec == mid_record_day(rec.year, rec.month):
        return "월중"
    if rec == eom_record_day(rec.year, rec.month):
        return "월말"
    return None


def round_from_last_buy(last_buy: date):
    """최종매수일에서 (배당락일, 기준일)을 계산한다."""
    ex = next_biz(last_buy)
    return ex, next_biz(ex)


def rule_round(timing: str, year: int, month: int):
    """규칙으로 그 달 회차의 (최종매수일, 배당락일, 기준일)을 계산한다."""
    rec = mid_record_day(year, month) if timing == "월중" else eom_record_day(year, month)
    ex = prev_biz(rec)
    return prev_biz(ex), ex, rec
