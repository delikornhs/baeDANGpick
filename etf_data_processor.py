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
LATEST_FILE = OUT_DIR / "latest.json"
JS_FILE = OUT_DIR / "etf_data.js"


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


# ── 분배 주기 분류 ──
def classify_frequency(isin: str, history: dict) -> str:
    """
    배당락일 간격 중앙값으로 주기를 결정.
      ~45일  → 월배당
      ~100일 → 분기배당
      ~190일 → 반기배당
      그 이상 → 연배당
    데이터 2건 미만이면 이름 기반으로 추정.
    """
    if isin not in history:
        return "분기배당이상"

    records = history[isin]
    dates = sorted(records.keys())

    if len(dates) < 2:
        # 데이터 1건: 이름 기반 추정
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
        name = list(records.values())[0].get("name", "")
        return classify_frequency_by_name(name)

    gaps.sort()
    median_gap = gaps[len(gaps) // 2]

    if median_gap <= 45:
        return "월배당"
    else:
        return "분기배당이상"


def classify_frequency_by_name(name: str) -> str:
    """이력 없을 때 이름 기반 추정 → 월배당추정 또는 분기배당이상"""
    monthly_kw = [
        "커버드콜", "배당다우존스", "배당귀족", "배당성장", "고배당",
        "리츠", "하이일드", "회사채", "국채", "인컴", "위클리", "데일리",
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
    가장 최근 배당락일 기준으로 latest.json 생성.
    target_month: 'YYYY-MM' 형식으로 특정 월 지정 가능 (기본: 최신)
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

    # target_month 필터링
    if target_month:
        target_dates = [d for d in all_ex_dates if d.startswith(target_month)]
    else:
        # 가장 최근 월의 모든 배당락일
        latest_month = all_ex_dates[-1][:7]
        target_dates = [d for d in all_ex_dates if d.startswith(latest_month)]

    print(f"대상 배당락일: {target_dates}")

    latest = []
    for isin, records in history.items():
        for ex_date, r in records.items():
            if ex_date in target_dates:
                freq = classify_frequency(isin, history)
                if freq == "분기배당이상":
                    # 이력 기반 분기배당이상이어도 이름으로 재확인 불필요
                    pass
                name = r.get("name", "")
                ex = r["ex"]
                timing = ""
                if freq in ("월배당", "월배당추정"):
                    day = int(ex[8:10]) if len(ex) >= 10 else 31
                    timing = "월중" if day <= 20 else "월말"
                latest.append({
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
                })

    # 분배금 추이 추가
    for item in latest:
        isin = item["isin"]
        trend = []
        if isin in history:
            # 최근 12개월 이력 정렬
            sorted_records = sorted(
                history[isin].items(),
                key=lambda x: x[0]
            )[-12:]
            for ex_key, rec in sorted_records:
                trend.append({
                    "ex_date": ex_key,
                    "dist":    rec["dist"],
                })
        item["trend"] = trend

    latest.sort(key=lambda x: x["name"])

    with open(LATEST_FILE, "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=2)

    print(f"✅ {len(latest)}개 ETF")
    print(f"💾 저장: {LATEST_FILE}")
    return latest


def build_js(latest: list, price_date: str = ""):
    """latest.json을 사이트에 바로 삽입할 etf_data.js로 변환. price/rate는 호출 전에 설정."""
    print("\n" + "=" * 50)
    print("📝 JS 데이터 파일 생성")
    print("=" * 50)

    # ETF_END (월말), ETF_MID (월중) 분리
    end_list, mid_list = [], []
    for item in latest:
        ex_day = int(item["ex_date"][8:10]) if len(item["ex_date"]) >= 10 else 0
        if ex_day <= 20:
            mid_list.append(item)
        else:
            end_list.append(item)

    def to_js_array(lst, var_name):
        items = []
        for e in lst:
            name_esc = e["name"].replace("'", "\\'").replace('"', '&quot;')
            trend_js = json.dumps(e.get("trend", []), ensure_ascii=False)
            items.append(
                f"{{isin:'{e['isin']}',code:'{e['code']}',name:'{name_esc}',"
                f"brand:'{e['brand']}',type:'{e['type']}',freq:'{e['freq']}',timing:'{e.get('timing','')}', "
                f"ex:'{e['ex_date']}',pay:'{e['pay_date']}',"
                f"dist:{e['dist']},price:{e['price']},rate:{e['rate']},"
                f"trend:{trend_js}}}"
            )
        return f"const {var_name} = [\n" + ",\n".join(items) + "\n];"

    def most_common_notice(lst):
        counts = defaultdict(int)
        for e in lst:
            nd = e.get("notice_date", "")
            if nd:
                counts[nd] += 1
        return max(counts, key=counts.get) if counts else ""

    mid_notice = most_common_notice(mid_list)
    end_notice = most_common_notice(end_list)

    header = f'const PRICE_DATE = "{price_date}";\n'
    header += f'const MID_NOTICE_DATE = "{mid_notice}";\n'
    header += f'const END_NOTICE_DATE = "{end_notice}";\n\n'
    js_content = header + to_js_array(end_list, "ETF_END") + "\n\n" + to_js_array(mid_list, "ETF_MID")

    with open(JS_FILE, "w", encoding="utf-8") as f:
        f.write(js_content)

    size_kb = JS_FILE.stat().st_size // 1024
    print(f"✅ ETF_END: {len(end_list)}개, ETF_MID: {len(mid_list)}개")
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
        # fallback: 마커가 있는 HTML 파일 탐색
        for f in sorted(BASE_DIR.glob("*.html")):
            if "const ETF_END" in f.read_text(encoding="utf-8", errors="replace"):
                html_path = f
                break
        else:
            print("⚠️  HTML 파일을 찾지 못했습니다.")
            return
    js_content = JS_FILE.read_text(encoding="utf-8")

    html = html_path.read_text(encoding="utf-8", errors="replace")

    start = html.find("const ETF_END")
    # PRICE_DATE가 있으면 그 앞부터 교체
    pd_pos = html.find("const PRICE_DATE")
    if pd_pos != -1 and pd_pos < start:
        start = pd_pos

    end = html.find("const TODAY")
    if start == -1 or end == -1:
        print(f"⚠️  교체 마커를 찾지 못했습니다. (ETF_END={start}, TODAY={end})")
        return

    new_html = html[:start] + js_content.strip() + "\n\n\n" + html[end:]
    html_path.write_text(new_html, encoding="utf-8")
    print(f"✅ {html_path.name} 업데이트 완료")


# ── 실행 ──
if __name__ == "__main__":
    import sys

    args = sys.argv[1:]

    # --prices-only: latest.json 기준 종가만 업데이트
    if "--prices-only" in args:
        if not LATEST_FILE.exists():
            print(f"❌ {LATEST_FILE} 없음. 먼저 전체 실행하세요.")
            exit(1)

        with open(LATEST_FILE, encoding="utf-8") as f:
            latest = json.load(f)

        codes = list({item["code"] for item in latest})
        price_map, price_date = fetch_naver_prices(codes)

        # 현재 종가만 price 필드에 반영 (rate는 기존 공시일자 기준 값 유지)
        for item in latest:
            p = price_map.get(item["code"]) or price_map.get(item["isin"])
            if p and p > 0:
                item["price"] = p

        with open(LATEST_FILE, "w", encoding="utf-8") as f:
            json.dump(latest, f, ensure_ascii=False, indent=2)

        build_js(latest, price_date)
        inject_html()

        print("\n✅ 종가 업데이트 완료!")
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
