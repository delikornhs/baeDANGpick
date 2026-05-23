"""
ETF 분배금 데이터 처리 스크립트
================================
사용법:
  1. KIND에서 다운받은 XLS 파일들을 data/raw/ 폴더에 넣기
  2. python etf_data_processor.py
  3. data/output/ 폴더에 결과 생성

폴더 구조:
  data/
    raw/          ← KIND에서 받은 XLS 파일들 (월별로 모두)
    output/
      history.json     ← 전체 분배금 이력 (주기 분류 포함)
      latest.json      ← 이번달 현황 (사이트에서 사용)
      etf_data.js      ← 사이트에 직접 삽입할 JS 데이터
"""

import csv
import json
import os
import glob
import re
import subprocess
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

try:
    import xlrd
    XLRD_AVAILABLE = True
except ImportError:
    XLRD_AVAILABLE = False


# ── 경로 설정 ──
BASE_DIR = Path(__file__).parent
RAW_DIR = BASE_DIR / "data" / "raw"
OUT_DIR = BASE_DIR / "data" / "output"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR.mkdir(parents=True, exist_ok=True)

HISTORY_FILE = OUT_DIR / "history.json"
LATEST_FILE  = OUT_DIR / "latest.json"
JS_FILE      = OUT_DIR / "etf_data.js"
ETF_META_FILE = OUT_DIR / "etf_meta.json"

# ── 브랜드 → 실제 운용사 매핑 ──
BRAND_TO_COMPANY = {
    "KODEX":      "삼성자산운용",
    "TIGER":      "미래에셋자산운용",
    "RISE":       "KB자산운용",
    "SOL":        "신한자산운용",
    "ACE":        "한국투자신탁운용",
    "PLUS":       "한화자산운용",
    "ARIRANG":    "한화자산운용",
    "KIWOOM":     "키움투자자산운용",
    "KOSEF":      "키움투자자산운용",
    "HANARO":     "NH아문디자산운용",
    "KoAct":      "교보악사자산운용",
    "파워":        "교보악사자산운용",
    "FOCUS":      "동양자산운용",
    "마이티":      "흥국자산운용",
    "WON":        "우리자산운용",
    "TIMEFOLIO":  "타임폴리오자산운용",
    "타임폴리오":  "타임폴리오자산운용",
    "대신":        "대신자산운용",
    "1Q":         "하나자산운용",
    "HK":         "하이자산운용",
}


# ── XLS 파싱 (KIND HTML-as-XLS 형식) ──
def parse_xls(xls_path: Path) -> list:
    """KIND에서 받은 HTML-as-XLS 파일에서 ETF 분배금 데이터 추출"""
    results = []
    try:
        with open(xls_path, "r", encoding="utf-8") as f:
            content = f.read()
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", content, re.DOTALL | re.IGNORECASE)
        for row_html in rows:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.DOTALL | re.IGNORECASE)
            cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if (len(cells) >= 5
                    and cells[0].startswith("KR")
                    and cells[1]
                    and re.match(r"^\d+$", cells[4])):
                results.append({
                    "isin":     cells[0],
                    "code":     cells[0][3:9],
                    "name":     cells[1],
                    "ex_date":  cells[2],
                    "pay_date": cells[3],
                    "dist":     int(cells[4]),
                })
    except Exception as e:
        print(f"  ⚠️  파싱 오류 {xls_path.name}: {e}")
    return results


# ── XLS → CSV 변환 (LibreOffice fallback) ──
def xls_to_csv(xls_path: Path) -> Path:
    """LibreOffice로 XLS를 CSV로 변환"""
    csv_path = OUT_DIR / (xls_path.stem + ".csv")
    if csv_path.exists():
        return csv_path
    result = subprocess.run(
        ["libreoffice", "--headless", "--convert-to", "csv",
         "--outdir", str(OUT_DIR), str(xls_path)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  ⚠️  변환 실패: {xls_path.name}")
        return None
    return csv_path


# ── CSV 파싱 ──
def parse_csv(path: Path) -> list:
    """CSV에서 ETF 분배금 데이터 추출"""
    results = []
    try:
        with open(path, encoding="utf-8") as f:
            for row in csv.reader(f):
                if (len(row) >= 5
                        and row[0].startswith("KR")
                        and row[1].strip()
                        and row[4].strip().isdigit()):
                    results.append({
                        "isin":     row[0].strip(),
                        "code":     row[0].strip()[3:9],
                        "name":     row[1].strip(),
                        "ex_date":  row[2].strip(),
                        "pay_date": row[3].strip(),
                        "dist":     int(row[4].strip()),
                    })
    except Exception as e:
        print(f"  ⚠️  파싱 오류 {path.name}: {e}")
    return results


# ── 파일명에서 날짜 추출 ──
def extract_date_from_filename(filename: str) -> str:
    """파일명에서 날짜 추출 → 'YYYY-MM-DD' 반환. (2026.04.28) / 2026_04_28 형식 지원."""
    m = re.search(r"(\d{4})[._\-](\d{2})[._\-](\d{2})", filename)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


# ── 브랜드 추출 ──
def get_brand(name: str) -> str:
    known = [
        "KODEX", "TIGER", "RISE", "SOL", "ACE", "PLUS", "KIWOOM",
        "HANARO", "KoAct", "FOCUS", "1Q", "HK", "마이티", "파워",
        "WON", "TIMEFOLIO", "타임폴리오", "대신", "KOSEF", "ARIRANG",
    ]
    for b in known:
        if name.upper().startswith(b.upper()):
            return b
    return name.split(" ")[0][:6]


# ── 유형 분류 ──
def get_type(name: str) -> str:
    if any(x in name for x in ["커버드콜", "CoveredCall"]):
        return "커버드콜"
    if any(x in name for x in ["리츠", "부동산인프라", "Realty", "글로벌리얼티"]):
        return "리츠"
    if any(x in name for x in ["배당", "Dividend", "고배당"]):
        return "배당"
    if any(x in name for x in ["국채", "회사채", "채권", "하이일드", "Bond"]):
        return "채권"
    return "기타"


RECENCY_DAYS = 60  # 최근 배당락일이 이 일수 이내여야 월배당/월배당추정으로 분류


def is_recent(ex_date_str: str) -> bool:
    """배당락일이 오늘 기준 RECENCY_DAYS 이내인지 확인."""
    try:
        ex = datetime.strptime(ex_date_str, "%Y-%m-%d")
        return (datetime.now() - ex).days <= RECENCY_DAYS
    except ValueError:
        return False


# ── 분배 주기 분류 ──
def classify_frequency(isin: str, history: dict) -> str:
    """
    배당락일 간격 중앙값으로 주기를 결정.
      ~45일  → 월배당
      그 이상 → 분기배당이상
    데이터 2건 미만이면 이름 기반으로 추정.
    단, 가장 최근 배당락일이 60일 이상 지났으면 월배당/월배당추정 분류 제외.
    """
    if isin not in history:
        return "분기배당이상"

    records = history[isin]
    dates = sorted(records.keys())
    latest_date = dates[-1]

    if len(dates) < 2:
        # 데이터 1건: 최근성 확인 후 이름 기반 추정
        if not is_recent(latest_date):
            return "분기배당이상"
        name = list(records.values())[0].get("name", "")
        return classify_frequency_by_name(name)

    # 연속 배당락일 간격(일) 계산
    gaps = []
    for i in range(1, len(dates)):
        try:
            d0 = datetime.strptime(dates[i - 1], "%Y-%m-%d")
            d1 = datetime.strptime(dates[i], "%Y-%m-%d")
            gap = (d1 - d0).days
            if 10 < gap < 400:   # 비정상적인 간격 제외
                gaps.append(gap)
        except ValueError:
            pass

    if not gaps:
        if not is_recent(latest_date):
            return "분기배당이상"
        name = list(records.values())[0].get("name", "")
        return classify_frequency_by_name(name)

    gaps.sort()
    median_gap = gaps[len(gaps) // 2]

    if median_gap <= 45:
        # 최근 60일 이내 지급 이력 없으면 월배당으로 분류하지 않음
        if not is_recent(latest_date):
            return "분기배당이상"
        return "월배당"
    else:
        return "분기배당이상"


def classify_frequency_by_name(name: str) -> str:
    """이력 없을 때 이름 기반 추정 → 월배당추정 또는 분기배당이상
    채권 ETF(이름에 '채권' 포함)는 월배당 추정 제외.
    """
    # 채권 ETF 제외: 이름에 '채권' 포함 시 추정 불가
    bond_kw = ["채권"]
    for kw in bond_kw:
        if kw in name:
            return "분기배당이상"

    monthly_kw = [
        "커버드콜", "배당다우존스", "배당귀족", "배당성장", "고배당",
        "리츠", "하이일드", "인컴", "위클리", "데일리",
        "배당증가", "배당킹", "배당플러스", "배당TOP", "인프라",
    ]
    for kw in monthly_kw:
        if kw in name:
            return "월배당추정"
    return "분기배당이상"


# ── 메인 처리 함수 ──
def build_history():
    """
    raw/ 폴더의 모든 XLS 파일을 처리해 history.json 구축.
    - 같은 파트너스, 같은 달에 여러 파일 있으면 → 파일명 날짜 늦은 것 우선
    - 정정공시('정정' 포함)는 원본보다 우선 적용
    """
    print("=" * 50)
    print("📂 XLS 파일 처리 시작")
    print("=" * 50)

    # 하위 폴더 포함 전체 탐색 (**/*.xls)
    xls_files = sorted(RAW_DIR.rglob("*.xls")) + sorted(RAW_DIR.rglob("*.XLS"))
    if not xls_files:
        print(f"⚠️  {RAW_DIR} 폴더에 XLS 파일이 없습니다.")
        return {}

    # 기존 history 로드
    history = {}
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, encoding="utf-8", errors="replace") as f:
            history = json.load(f)
        print(f"기존 history 로드: {len(history)}개 종목\n")

    # 파일별 처리
    # 같은 배당락일에 여러 파일이 있으면 파일명 날짜 늦은 것이 덮어씀
    # 정정공시는 파일명 정렬 시 '정정'이 포함되어 있어 sorted()로 나중에 처리됨
    total_records = 0
    for xls_path in xls_files:
        print(f"처리 중: {xls_path.name}")

        # xlrd로 직접 파싱, 실패 시 CSV 변환 fallback
        if XLRD_AVAILABLE:
            records = parse_xls(xls_path)
        else:
            csv_path = xls_to_csv(xls_path)
            records = parse_csv(csv_path) if csv_path else []
        if not records:
            print(f"  → 데이터 없음")
            continue

        ex_dates = defaultdict(int)
        for r in records:
            ex_dates[r["ex_date"]] += 1
        for d, cnt in sorted(ex_dates.items()):
            print(f"  → {d}: {cnt}개")

        notice_date = extract_date_from_filename(xls_path.name)
        for r in records:
            isin = r["isin"]
            ex_key = r["ex_date"]
            if isin not in history:
                history[isin] = {}
            history[isin][ex_key] = {
                "dist":        r["dist"],
                "ex":          r["ex_date"],
                "pay":         r["pay_date"],
                "name":        r["name"],
                "code":        r["code"],
                "notice_date": notice_date,
            }
            total_records += 1

    print(f"\n✅ 처리 완료: 총 {total_records}건, 종목 {len(history)}개")

    # history 저장
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print(f"💾 저장: {HISTORY_FILE}")

    return history


def build_latest(history: dict, target_month: str = None):
    """
    전체 ETF를 대상으로 최신 데이터 생성.
    - 현재 기간(최근 월중/월말) 해당 ETF: current=True
    - 나머지 ETF: 가장 최근 기록 사용, current=False
    target_month: 'YYYY-MM' 형식으로 현재 기간 기준월 지정 가능
    """
    print("\n" + "=" * 50)
    print("📊 최신 데이터 생성")
    print("=" * 50)

    # 전체 배당락일 목록
    all_ex_dates = sorted(set(
        ex for d in history.values() for ex in d.keys()
        if re.match(r"\d{4}-\d{2}-\d{2}", ex)
    ))

    if not all_ex_dates:
        print("⚠️  데이터 없음")
        return []

    # 현재 기간 날짜 결정
    if target_month:
        target_dates = set(d for d in all_ex_dates if d.startswith(target_month))
    else:
        # 월중(20일 이하)과 월말(21일 이상) 각각 독립적으로 최신 날짜 선택
        mid_dates = [d for d in all_ex_dates if int(d[8:10]) <= 20]
        end_dates = [d for d in all_ex_dates if int(d[8:10]) > 20]
        target_dates = set()
        if mid_dates:
            target_dates.add(mid_dates[-1])
        if end_dates:
            target_dates.add(end_dates[-1])

    print(f"현재 기간 배당락일: {sorted(target_dates)}")

    def make_entry(isin, r, ex, is_current):
        freq = classify_frequency(isin, history)
        name = r.get("name", "")
        timing = ""
        if freq in ("월배당", "월배당추정"):
            day = int(ex[8:10]) if len(ex) >= 10 else 31
            timing = "월중" if day <= 20 else "월말"
        return {
            "isin":        isin,
            "code":        r.get("code", isin[3:9]),
            "name":        name,
            "brand":       get_brand(name),
            "type":        get_type(name),
            "freq":        freq,
            "timing":      timing,
            "ex_date":     ex,
            "pay_date":    r["pay"],
            "dist":        r["dist"],
            "price":       0,
            "rate":        0.0,
            "notice_date": r.get("notice_date", ""),
            "current":     is_current,
        }

    latest = []
    seen_isins = set()

    # 1단계: 현재 기간 ETF (current=True)
    for isin, records in history.items():
        for td in sorted(target_dates):
            if td in records and isin not in seen_isins:
                r = records[td]
                latest.append(make_entry(isin, r, r["ex"], True))
                seen_isins.add(isin)
                break

    # 2단계: 나머지 ETF (가장 최근 기록, current=False)
    for isin, records in history.items():
        if isin in seen_isins or not records:
            continue
        latest_ex_key = sorted(records.keys())[-1]
        r = records[latest_ex_key]
        latest.append(make_entry(isin, r, r["ex"], False))
        seen_isins.add(isin)

    # 분배금 추이 추가 (최근 12개월)
    for item in latest:
        isin = item["isin"]
        trend = []
        if isin in history:
            sorted_records = sorted(history[isin].items(), key=lambda x: x[0])[-12:]
            for ex_key, rec in sorted_records:
                trend.append({"ex_date": ex_key, "dist": rec["dist"]})
        item["trend"] = trend

    latest.sort(key=lambda x: x["name"])

    with open(LATEST_FILE, "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=2)

    current_cnt = sum(1 for e in latest if e["current"])
    print(f"✅ 전체 {len(latest)}개 ETF (현재 기간 {current_cnt}개 포함)")
    print(f"💾 저장: {LATEST_FILE}")
    return latest


def build_js(latest: list, price_date: str = ""):
    """latest.json을 사이트에 바로 삽입할 etf_data.js로 변환. price/rate는 호출 전에 설정."""
    print("\n" + "=" * 50)
    print("📝 JS 데이터 파일 생성")
    print("=" * 50)

    def most_common_notice(lst):
        counts = defaultdict(int)
        for e in lst:
            nd = e.get("notice_date", "")
            if nd:
                counts[nd] += 1
        return max(counts, key=counts.get) if counts else ""

    # 현재 기간 ETF에서 공시일 계산
    current_mid = [e for e in latest if e.get("current") and int(e["ex_date"][8:10]) <= 20]
    current_end = [e for e in latest if e.get("current") and int(e["ex_date"][8:10]) > 20]
    mid_notice = most_common_notice(current_mid)
    end_notice = most_common_notice(current_end)

    # ETF_ALL 단일 배열 (current 플래그 포함)
    def to_js_array_all(lst):
        items = []
        for e in lst:
            name_esc = e["name"].replace("'", "\\'").replace('"', '&quot;')
            trend_js = json.dumps(e.get("trend", []), ensure_ascii=False)
            current_js = "true" if e.get("current") else "false"
            stab_js = json.dumps({
                "score":          e.get("stab_score",      ""),
                "variation":      e.get("stab_variation",  0),
                "trend":          e.get("stab_trend",      ""),
                "trendPct":       e.get("trend_change_pct",0),
                "level":          e.get("stab_level",      ""),
                "levelDist":      e.get("stab_level_dist", ""),
                "annualDist":     e.get("annual_dist",     0),
                "avgMonthlyRate": e.get("avg_monthly_rate",0),
                "groupAvgRate":   e.get("group_avg_rate",  0),
                "avgMonthlyDist": e.get("avg_monthly_dist",0),
                "groupAvgDist":   e.get("group_avg_dist",  0),
                "peerGroup":      e.get("peer_group",      ""),
            }, ensure_ascii=False)
            manager_esc = e.get("manager", e["brand"]).replace("'", "\\'")
            items.append(
                f"{{isin:'{e['isin']}',code:'{e['code']}',name:'{name_esc}',"
                f"brand:'{e['brand']}',manager:'{manager_esc}',"
                f"type:'{e['type']}',freq:'{e['freq']}',"
                f"timing:'{e.get('timing','')}', "
                f"ex:'{e['ex_date']}',pay:'{e['pay_date']}',"
                f"dist:{e['dist']},price:{e['price']},rate:{e['rate']},"
                f"listedDate:'{e.get('listed_date','')}', "
                f"ret1w:{e.get('return_1w',0)},ret1m:{e.get('return_1m',0)},ret3m:{e.get('return_3m',0)},"
                f"ret6m:{e.get('return_6m',0)},ret1y:{e.get('return_1y',0)},"
                f"retListed:{e.get('return_listed',0)},"
                f"tret1w:{e.get('total_return_1w',0)},tret1m:{e.get('total_return_1m',0)},tret3m:{e.get('total_return_3m',0)},"
                f"tret6m:{e.get('total_return_6m',0)},tret1y:{e.get('total_return_1y',0)},"
                f"tretListed:{e.get('total_return_listed',0)},"
                f"current:{current_js},trend:{trend_js},stab:{stab_js}}}"
            )
        return "const ETF_ALL = [\n" + ",\n".join(items) + "\n];"

    # 주간 범위 계산 (price_date 기준 월~금)
    price_dt = datetime.strptime(price_date, "%Y-%m-%d")
    mon_offset = price_dt.weekday()          # 0=월 … 4=금
    week_start = (price_dt - timedelta(days=mon_offset)).strftime("%Y-%m-%d")
    week_end   = (price_dt + timedelta(days=max(0, 4 - mon_offset))).strftime("%Y-%m-%d")

    header = f'const PRICE_DATE = "{price_date}";\n'
    header += f'const MID_NOTICE_DATE = "{mid_notice}";\n'
    header += f'const END_NOTICE_DATE = "{end_notice}";\n'
    header += f'const WEEK_START = "{week_start}";\n'
    header += f'const WEEK_END = "{week_end}";\n\n'
    # ETF_END, ETF_MID는 JS에서 ETF_ALL로부터 파생
    derive = ('const ETF_END = ETF_ALL.filter(e => e.current && e.timing === "월말");\n'
              'const ETF_MID = ETF_ALL.filter(e => e.current && e.timing === "월중");\n')
    js_content = header + to_js_array_all(latest) + "\n\n" + derive

    with open(JS_FILE, "w", encoding="utf-8") as f:
        f.write(js_content)

    size_kb = JS_FILE.stat().st_size // 1024
    print(f"✅ 전체 {len(latest)}개 (현재 기간 월중 {len(current_mid)}개 / 월말 {len(current_end)}개)")
    print(f"💾 저장: {JS_FILE} ({size_kb}KB)")


def prev_business_day(date_str: str) -> str:
    """YYYY-MM-DD 기준 직전 영업일 (주말만 제외, 공휴일 미고려)"""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    d -= timedelta(days=1)
    while d.weekday() >= 5:  # 5=토, 6=일
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def fetch_naver_historical_price(code: str, target_date: str, headers: dict) -> int:
    """
    target_date(YYYY-MM-DD) 이하 가장 가까운 거래일 종가 조회.
    공휴일 포함 시장 휴장일은 데이터가 없으므로 그 직전 거래일 종가를 반환.
    Naver Finance fchart API (최근 60거래일).
    """
    target_nodash = target_date.replace("-", "")
    url = (
        f"https://fchart.stock.naver.com/sise.nhn"
        f"?symbol={code}&timeframe=day&count=60&requestType=0"
    )
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("euc-kr", errors="replace")
        # 형식: <item data="YYYYMMDD|open|high|low|close|volume" />
        # target_date 이하 가장 최근 거래일 선택 (정렬 순서 무관)
        best_date, best_price = "", 0
        for m in re.finditer(r'<item data="(\d{8})\|[^|]+\|[^|]+\|[^|]+\|(\d+)\|', content):
            d = m.group(1)
            if d <= target_nodash and d > best_date:
                best_date = d
                best_price = int(m.group(2))
        if best_price:
            return best_price
    except Exception:
        pass
    return 0


def fetch_etf_meta(codes: list) -> dict:
    """
    네이버 금융 ETF 페이지에서 기초지수명·상장일 조회 후 etf_meta.json 캐시.
    이미 캐시된 종목은 재조회하지 않음.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://finance.naver.com/",
    }

    # 기존 캐시 로드
    meta: dict = {}
    if ETF_META_FILE.exists():
        with open(ETF_META_FILE, encoding="utf-8") as f:
            meta = json.load(f)

    missing = [c for c in codes if c not in meta or not meta[c].get("listed_date")]
    if not missing:
        return meta

    print(f"\n메타 데이터 조회: {len(missing)}개 종목 (신규/미완성)")

    for i, code in enumerate(missing):
        try:
            url = f"https://finance.naver.com/item/main.nhn?code={code}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                content = resp.read().decode("utf-8", errors="replace")

            # 상장일 파싱 (2002년 10월 14일 형식)
            date_m = re.search(
                r'상장일.*?<td>(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일',
                content, re.DOTALL)
            # 운용사 파싱 (title 속성에서 추출)
            mgr_m = re.search(
                r'운용사.*?title="([^"]{2,40})"',
                content, re.DOTALL)

            if date_m:
                listed_date = f"{date_m.group(1)}-{int(date_m.group(2)):02d}-{int(date_m.group(3)):02d}"
            else:
                listed_date = ""
            mgr_raw = mgr_m.group(1).strip() if mgr_m else ""
            # "(주)", "(유)" 등 법인형태 제거
            manager = re.sub(r'\s*[（(][가-힣]{1,2}[)）]\s*$', '', mgr_raw).strip()

            meta[code] = {"listed_date": listed_date, "manager": manager}
        except Exception:
            meta[code] = {"listed_date": "", "manager": ""}

        time.sleep(0.2)
        if (i + 1) % 50 == 0:
            print(f"  진행: {i+1}/{len(missing)}")

    with open(ETF_META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"💾 메타 캐시 저장: {ETF_META_FILE}")
    return meta


def days_since_listed(listed_date_str: str, fallback: int = 400) -> int:
    """상장일로부터 현재까지 필요한 영업일 수 계산. 최대 3000일(약 12년)."""
    if not listed_date_str:
        return fallback
    try:
        listed = datetime.strptime(listed_date_str, "%Y-%m-%d")
        calendar_days = (datetime.now() - listed).days + 20  # 여유 20일
        trading_days = int(calendar_days * 5 / 7) + 10       # 영업일 환산
        return min(max(trading_days, fallback), 3000)
    except Exception:
        return fallback


def fetch_daily_price_history(code: str, days: int, headers: dict) -> list:
    """
    네이버 fchart API로 일별 종가 이력 반환.
    Returns: [(date_str 'YYYY-MM-DD', close_price int), ...] ascending
    """
    url = (f"https://fchart.stock.naver.com/sise.nhn"
           f"?symbol={code}&timeframe=day&count={days}&requestType=0")
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("euc-kr", errors="replace")
        result = []
        for m in re.finditer(r'<item data="(\d{8})\|[^|]+\|[^|]+\|[^|]+\|(\d+)\|', content):
            d = m.group(1)
            price = int(m.group(2))
            if price > 0:
                result.append((f"{d[:4]}-{d[4:6]}-{d[6:]}", price))
        return sorted(result)
    except Exception:
        return []


def find_price_at_or_before(daily: list, target_date: str) -> int:
    """일별 이력에서 target_date 이하 가장 최근 종가 반환."""
    best = 0
    for date_str, price in daily:
        if date_str <= target_date:
            best = price
        else:
            break
    return best


def calc_returns(item: dict, daily: list, history: dict) -> dict:
    """
    일별 이력으로 주가 수익률 및 분배금 포함 총수익률 계산.
    periods: 1W(7일) / 1M(30일) / 3M(91일) / 6M(182일) / 1Y(365일)
    """
    current_price = item.get("price", 0)
    if not current_price or not daily:
        return {}

    isin = item["isin"]
    now  = datetime.now()
    ret  = {}

    # 상장 이후 (가장 오래된 일별 데이터 기준 = 상장일 종가)
    if daily:
        oldest_date, oldest_price = daily[0]
        if oldest_price > 0:
            ret["price_listed"] = oldest_price
            pr = round((current_price - oldest_price) / oldest_price * 100, 2)
            ret["return_listed"] = pr
            dist_sum = 0
            if isin in history:
                dist_sum = sum(
                    rec["dist"] for ex_k, rec in history[isin].items()
                    if ex_k >= oldest_date
                )
            ret["total_return_listed"] = round(
                (current_price - oldest_price + dist_sum) / oldest_price * 100, 2)

    for label, days in [("1w", 7), ("1m", 30), ("3m", 91), ("6m", 182), ("1y", 365)]:
        target = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        past_price = find_price_at_or_before(daily, target)
        if not past_price:
            continue
        ret[f"price_{label}"] = past_price
        pr = round((current_price - past_price) / past_price * 100, 2)
        ret[f"return_{label}"] = pr
        dist_sum = 0
        if isin in history:
            dist_sum = sum(
                rec["dist"] for ex_k, rec in history[isin].items()
                if ex_k >= target
            )
        ret[f"total_return_{label}"] = round(
            (current_price - past_price + dist_sum) / past_price * 100, 2)

    return ret


def calc_stability_metrics(isin: str, history: dict, current_price: int = 0) -> dict:
    """
    분배금 안정성 지표 계산.
    - stab_score  : 매우 안정 / 안정 / 보통 / 주의 / 데이터 부족
    - stab_trend  : 증가 / 유지 / 감소 / 데이터 부족
    - stab_level  : 보수적 / 일반적 / 공격적 / 주의
    """
    result = {
        "stab_score": "", "stab_variation": 0.0,
        "stab_trend": "", "trend_change_pct": 0.0,
        "stab_level": "", "annual_dist": 0,
        "avg_monthly_dist": 0.0, "avg_monthly_rate": 0.0,
    }
    if isin not in history:
        return result

    records = history[isin]
    now_str   = datetime.now().strftime("%Y-%m-%d")
    jan1_str  = datetime.now().strftime("%Y-01-01")   # 올해 1월 1일
    six_ago   = (datetime.now() - timedelta(days=182)).strftime("%Y-%m-%d")
    three_ago = (datetime.now() - timedelta(days=91)).strftime("%Y-%m-%d")

    sorted_keys = sorted(records.keys())
    year_dists  = [records[k]["dist"] for k in sorted_keys if k >= jan1_str]  # 올해 누적
    six_dists   = [records[k]["dist"] for k in sorted_keys if k >= six_ago]
    recent3     = [records[k]["dist"] for k in sorted_keys if k >= three_ago]
    prev3       = [records[k]["dist"] for k in sorted_keys if six_ago <= k < three_ago]

    result["annual_dist"] = sum(year_dists)

    # ① 안정성: 최근 6개월 변동폭 / 평균
    if len(six_dists) >= 2:
        avg = sum(six_dists) / len(six_dists)
        if avg > 0:
            variation = (max(six_dists) - min(six_dists)) / avg * 100
            result["stab_variation"] = round(variation, 1)
            if   variation <= 15: result["stab_score"] = "변동 적음"
            elif variation <= 30: result["stab_score"] = "변동 보통"
            elif variation <= 50: result["stab_score"] = "변동 큼"
            else:                 result["stab_score"] = "변동 매우 큼"
    elif six_dists:
        result["stab_score"] = "데이터 부족"

    # ② 추세: 최근 3개월 vs 이전 3개월 평균
    if recent3 and prev3:
        r_avg = sum(recent3) / len(recent3)
        p_avg = sum(prev3)  / len(prev3)
        if p_avg > 0:
            chg = (r_avg - p_avg) / p_avg * 100
            result["trend_change_pct"] = round(chg, 1)
            if   chg >  10: result["stab_trend"] = "증가"
            elif chg < -10: result["stab_trend"] = "감소"
            else:           result["stab_trend"] = "유지"
    elif recent3:
        result["stab_trend"] = "데이터 부족"

    # ③ 평균 월분배금·분배율 (최근 6개월, 동일유형 그룹비교용)
    yr6_dists = [records[k]["dist"] for k in sorted_keys if k >= six_ago]
    if yr6_dists:
        avg_dist = sum(yr6_dists) / len(yr6_dists)
        result["avg_monthly_dist"] = round(avg_dist, 1)
        if current_price > 0:
            result["avg_monthly_rate"] = round(avg_dist / current_price * 100, 3)
    # stab_level 은 전체 ETF 처리 후 그룹 평균 대비로 별도 설정

    return result


def get_peer_group(item: dict) -> str:
    """ETF 동일유형 그룹 분류 (월분배 수준 비교용)"""
    freq = item.get("freq", "")
    typ  = item.get("type", "")
    if freq in ("월배당", "월배당추정"):
        if typ == "커버드콜": return "월배당(커버드콜)"
        if typ == "리츠":     return "월배당(리츠)"
        return "월배당(일반배당)"
    return "분기배당이상"


def fetch_naver_prices(codes: list) -> tuple:
    """
    네이버 금융 모바일 API로 ETF 전날 종가 일괄 조회.
    Returns: ({code: price}, price_date_str)
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://m.stock.naver.com/",
        "Accept": "application/json, text/plain, */*",
    }

    # 워크플로우가 17:30 KST(장 마감 후)에 실행되므로 오늘 날짜가 곧 종가 기준일
    price_date = datetime.now().strftime("%Y-%m-%d")

    prices = {}
    ok = fail = 0

    print(f"\n{'='*50}")
    print("📈 네이버 금융 전날 종가 조회")
    print(f"{'='*50}")
    print(f"총 {len(codes)}개 종목 조회 중...\n")

    for i, code in enumerate(codes):
        try:
            url = f"https://m.stock.naver.com/api/stock/{code}/basic"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            close_str = data.get("closePrice", "").replace(",", "")
            if close_str and close_str.lstrip("-").isdigit() and int(close_str) > 0:
                prices[code] = int(close_str)
                ok += 1
            else:
                fail += 1

            if (i + 1) % 100 == 0:
                print(f"  진행: {i+1}/{len(codes)} (성공 {ok}개)")

            time.sleep(0.05)

        except Exception:
            fail += 1
            time.sleep(0.05)

    print(f"✅ {ok}개 성공 / {fail}개 실패")
    print(f"📅 기준일: {price_date}")
    return prices, price_date


def update_prices(latest: list, price_map: dict):
    """
    주가 데이터를 업데이트하고 분배율 재계산.
    price_map: {isin: price} 또는 {code: price}
    실서비스에서 네이버/KRX API 연동 후 호출.
    """
    updated = 0
    for item in latest:
        price = price_map.get(item["isin"]) or price_map.get(item["code"])
        if price and price > 0:
            item["price"] = price
            item["rate"] = round(item["dist"] / price * 100, 2)
            updated += 1
    print(f"주가 업데이트: {updated}개")
    return latest


def print_frequency_summary(history: dict):
    """분배 주기 분류 결과 요약 출력"""
    print("\n" + "=" * 50)
    print("📈 분배 주기 분류 결과")
    print("=" * 50)
    counter = defaultdict(int)
    for isin in history:
        freq = classify_frequency(isin, history)
        if freq == "확인필요":
            # 최근 이름으로 재시도
            records = history[isin]
            if records:
                latest_rec = sorted(records.items())[-1][1]
                freq = classify_frequency_by_name(latest_rec.get("name", ""))
        counter[freq] += 1

    for freq, cnt in sorted(counter.items()):
        print(f"  {freq}: {cnt}개")


def inject_html():
    """
    etf_data.js 내용을 HTML 파일의 ETF_END/ETF_MID 블록에 자동 삽입.
    HTML과 etf_data.js 모두 같은 폴더 구조에 있다고 가정.
    """
    print("\n" + "=" * 50)
    print("🔧 HTML 자동 삽입")
    print("=" * 50)

    html_path = BASE_DIR / "index.html"
    if not html_path.exists():
        for f in sorted(BASE_DIR.glob("*.html")):
            txt = f.read_text(encoding="utf-8", errors="replace")
            if "const ETF_ALL" in txt or "const ETF_END" in txt:
                html_path = f
                break
        else:
            print("⚠️  HTML 파일을 찾지 못했습니다.")
            return
    js_content = JS_FILE.read_text(encoding="utf-8")

    html = html_path.read_text(encoding="utf-8", errors="replace")

    # ETF_ALL 또는 ETF_END 마커 찾기
    start = html.find("const ETF_ALL")
    if start == -1:
        start = html.find("const ETF_END")
    # PRICE_DATE가 있으면 그 앞부터 교체
    pd_pos = html.find("const PRICE_DATE")
    if pd_pos != -1 and (start == -1 or pd_pos < start):
        start = pd_pos

    end = html.find("const TODAY")
    if start == -1 or end == -1:
        print(f"⚠️  교체 마커를 찾지 못했습니다. (ETF_ALL={start}, TODAY={end})")
        return

    new_html = html[:start] + js_content.strip() + "\n\n\n" + html[end:]
    html_path.write_text(new_html, encoding="utf-8")
    print(f"✅ {html_path.name} 업데이트 완료")


# ── 실행 ──
if __name__ == "__main__":
    import sys

    args = sys.argv[1:]

    # --fetch-meta: 기초지수명·상장일 캐시 갱신 (수동 또는 주 1회 실행 권장)
    if "--fetch-meta" in args:
        if not LATEST_FILE.exists():
            print(f"❌ {LATEST_FILE} 없음.")
            exit(1)
        with open(LATEST_FILE, encoding="utf-8") as f:
            latest = json.load(f)
        codes = list({item["code"] for item in latest})
        # 강제 재조회를 위해 기존 캐시 초기화
        if ETF_META_FILE.exists():
            ETF_META_FILE.unlink()
        fetch_etf_meta(codes)
        print("✅ 메타 데이터 갱신 완료")
        exit(0)

    # --prices-only: 종가 + 수익률 + 안정성 지표 업데이트
    if "--prices-only" in args:
        if not LATEST_FILE.exists():
            print(f"❌ {LATEST_FILE} 없음. 먼저 전체 실행하세요.")
            exit(1)

        with open(LATEST_FILE, encoding="utf-8") as f:
            latest = json.load(f)

        # history.json 로드 (총수익률·안정성 계산에 필요)
        history_for_returns: dict = {}
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, encoding="utf-8") as f:
                history_for_returns = json.load(f)

        codes = list({item["code"] for item in latest})
        price_map, price_date = fetch_naver_prices(codes)

        # 현재 종가 반영
        for item in latest:
            p = price_map.get(item["code"]) or price_map.get(item["isin"])
            if p and p > 0:
                item["price"] = p

        # 일별 이력 조회 → 수익률 계산 (상장일 기준 필요 영업일 수만큼 동적 조회)
        hist_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://finance.naver.com/",
        }
        print(f"\n{'='*50}")
        print("📈 일별 이력 조회 및 수익률 계산")
        print(f"{'='*50}")
        ret_ok = ret_fail = 0
        for i, item in enumerate(latest):
            code   = item["code"]
            needed = days_since_listed(item.get("listed_date", ""))
            daily  = fetch_daily_price_history(code, needed, hist_headers)
            if daily:
                rets = calc_returns(item, daily, history_for_returns)
                for k, v in rets.items():
                    item[k] = v
                ret_ok += 1
            else:
                ret_fail += 1
            time.sleep(0.08)
            if (i + 1) % 100 == 0:
                print(f"  진행: {i+1}/{len(latest)} (성공 {ret_ok}개)")

        print(f"수익률 계산: {ret_ok}개 성공 / {ret_fail}개 실패")

        # 안정성 지표 계산 (분배율 수준은 공시일 전일 종가 기준)
        for item in latest:
            notice_prev_price = (
                int(item["dist"] / item["rate"] * 100)
                if item.get("rate", 0) > 0 else item.get("price", 0)
            )
            stab = calc_stability_metrics(
                item["isin"], history_for_returns, notice_prev_price)
            item.update(stab)

        # 피어그룹 평균 월분배율·월분배금 계산 → stab_level / stab_level_dist 설정
        peer_rates = defaultdict(list)
        peer_dists = defaultdict(list)
        for item in latest:
            g = get_peer_group(item)
            r = item.get("avg_monthly_rate", 0)
            d = item.get("avg_monthly_dist", 0)
            if r > 0: peer_rates[g].append(r)
            if d > 0: peer_dists[g].append(d)
        group_avg_rate = {g: sum(v)/len(v) for g, v in peer_rates.items() if v}
        group_avg_dist = {g: sum(v)/len(v) for g, v in peer_dists.items() if v}
        for item in latest:
            g        = get_peer_group(item)
            my_rate  = item.get("avg_monthly_rate", 0)
            ga_rate  = group_avg_rate.get(g, 0)
            my_dist  = item.get("avg_monthly_dist", 0)
            ga_dist  = group_avg_dist.get(g, 0)
            item["peer_group"]      = g
            item["group_avg_rate"]  = round(ga_rate, 3)
            item["group_avg_dist"]  = round(ga_dist, 1)
            if my_rate > 0 and ga_rate > 0:
                if   my_rate > ga_rate * 1.1: item["stab_level"]      = "평균보다 높음"
                elif my_rate < ga_rate * 0.9: item["stab_level"]      = "평균보다 낮음"
                else:                          item["stab_level"]      = "평균 수준"
            if my_dist > 0 and ga_dist > 0:
                if   my_dist > ga_dist * 1.1: item["stab_level_dist"] = "평균보다 높음"
                elif my_dist < ga_dist * 0.9: item["stab_level_dist"] = "평균보다 낮음"
                else:                          item["stab_level_dist"] = "평균 수준"

        # 메타 데이터 병합 (기초지수, 상장일, 운용사)
        meta_cache = {}
        if ETF_META_FILE.exists():
            with open(ETF_META_FILE, encoding="utf-8") as f:
                meta_cache = json.load(f)
        for item in latest:
            m = meta_cache.get(item["code"], {})
            item["listed_date"] = m.get("listed_date", "")
            # 운용사: 네이버 스크래핑 값 우선, 없으면 브랜드 매핑, 최종 fallback 브랜드명
            item["manager"] = (
                m.get("manager", "") or
                BRAND_TO_COMPANY.get(item["brand"], item["brand"])
            )
        with open(LATEST_FILE, "w", encoding="utf-8") as f:
            json.dump(latest, f, ensure_ascii=False, indent=2)

        build_js(latest, price_date)
        inject_html()

        print("\n✅ 종가·수익률·안정성 업데이트 완료!")
        print(f"   - price_date : {price_date}")
        print(f"   - etf_data.js: {JS_FILE}")
        exit(0)

    # 특정 월 지정 가능: python etf_data_processor.py 2026-04
    target_month = args[0] if args else None

    # 1. 전체 이력 구축
    history = build_history()

    if not history:
        print("처리할 데이터가 없습니다. data/raw/ 폴더에 XLS 파일을 넣어주세요.")
        exit(1)

    # 2. 주기 분류 요약
    print_frequency_summary(history)

    # 3. 최신 데이터 생성
    latest = build_latest(history, target_month)

    if not latest:
        print("최신 데이터가 없습니다.")
        exit(1)

    # 4. 현재 종가 조회 → price 필드 업데이트
    codes = list({item["code"] for item in latest})
    price_map, price_date = fetch_naver_prices(codes)
    for item in latest:
        p = price_map.get(item["code"]) or price_map.get(item["isin"])
        if p and p > 0:
            item["price"] = p
            item["rate"] = round(item["dist"] / p * 100, 2)  # 임시값 (다음 단계에서 재계산)

    # 5. 공시일자 전일 역사 종가로 분배율 재계산
    hist_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://finance.naver.com/",
    }
    print("\n" + "=" * 50)
    print("📊 공시일자 전일 종가로 분배율 계산")
    print("=" * 50)
    rate_updated = rate_fallback = 0
    for item in latest:
        nd = item.get("notice_date", "")
        if nd:
            prev_day = prev_business_day(nd)
            hist_price = fetch_naver_historical_price(item["code"], prev_day, hist_headers)
            if hist_price > 0:
                item["rate"] = round(item["dist"] / hist_price * 100, 2)
                rate_updated += 1
            else:
                rate_fallback += 1  # 현재 종가 임시값 유지
        else:
            rate_fallback += 1
    print(f"  → 공시일자 전일 기준: {rate_updated}개 | 현재 종가 fallback: {rate_fallback}개")

    # 6. latest.json 최종 저장 (rate 확정 후)
    with open(LATEST_FILE, "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=2)

    # 7. JS 파일 생성
    build_js(latest, price_date)

    # 8. HTML 자동 삽입
    inject_html()

    print("\n✅ 완료!")
    print(f"   - history.json : {HISTORY_FILE}")
    print(f"   - latest.json  : {LATEST_FILE}")
    print(f"   - etf_data.js  : {JS_FILE}")
