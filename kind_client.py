"""
KIND(kind.krx.co.kr) 공시 접근 공용 모듈.

kind_fetch.py(분배금 수집)와 kind_schedule.py(일정 파악)가 함께 사용한다.

■ 왜 검색만 브라우저를 쓰는가
  공시 검색 엔드포인트(/disclosure/details.do)는 curl·urllib 요청을 차단한다
  (헤더·쿠키·HTTP 버전을 맞춰도 '페이지 오류' 응답. TLS 지문 검사로 추정).
  반면 문서 조회·다운로드는 순수 HTTP로 잘 동작한다.
  → 검색만 Playwright로 처리하고 나머지는 urllib을 쓴다.

■ 검색 시 주의
  KIND의 fnSearch()는 #reportNmTemp 값을 읽어 #reportNm에 복사한다.
  reportNm에 직접 넣으면 덮어써져 필터가 걸리지 않는다. 반드시 reportNmTemp에 넣을 것.
"""

import re
import time
import urllib.request

BASE = "https://kind.krx.co.kr"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
SEARCH_URL = f"{BASE}/disclosure/details.do?method=searchDetailsMain"


# ── HTTP (문서 조회·다운로드) ──
def _get(url: str, data: str = None, retries: int = 3) -> str:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(
                url,
                data=data.encode() if data else None,
                headers={"User-Agent": UA, "Referer": BASE + "/"},
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def fetch_document(acptno: str) -> tuple:
    """
    공시 접수번호로 본문 HTML을 받아온다.

    Returns: (문서 HTML, 파일명) — 실패 시 (None, None)

    파일명은 KIND가 제공하는 값을 그대로 쓴다. etf_data_processor.py가
    파일명에서 공시일(notice_date)을 뽑아 분배율 계산에 사용하므로
    형식을 임의로 바꾸면 안 된다.
    """
    viewer = _get(
        f"{BASE}/common/disclsviewer.do?method=search"
        f"&acptno={acptno}&docno=&viewerhost=&viewerport="
    )

    # 본문 선택 목록: value='docNo|Y' 에서 Y = 최신본(정정 반영)
    opts = re.findall(r"<option value='(\d+)\|([NY])'([^>]*)>([^<]*)</option>", viewer)
    if not opts:
        return None, None
    latest = [o for o in opts if o[1] == "Y"]
    doc_no, _, _, doc_title = (latest[-1] if latest else opts[0])

    # 제출인(회사명) — 파일명 접두어.
    # 뷰어 JS가 fileName을 '[회사명] ' + 본문제목 으로 만든다:
    #   $("#docdownloadform").find("#fileName").val("[한국펀드파트너스] "+ ...)
    # 본문제목에는 '[정정]'이 붙을 수 있으므로 여기서 회사명을 따로 뽑아야 한다.
    m = re.search(r'\.val\(\s*"(\[[^\]]+\])\s*"\s*\+', viewer)
    corp = m.group(1) + " " if m else ""
    if not corp:  # fallback: <title>[회사명] ...
        m2 = re.search(r"<title>\s*(\[[^\]]+\])", viewer)
        corp = m2.group(1) + " " if m2 else ""

    # 문서 실제 경로
    path_html = _get(f"{BASE}/common/disclsviewer.do", f"method=searchContents&docNo={doc_no}")
    m3 = re.search(r'(https?://[^"\'\s]*external[^"\'\s]*\.htm)', path_html)
    if not m3:
        return None, None

    doc = _get(m3.group(1))
    file_name = (corp + doc_title.strip()).strip()
    return doc, file_name


# ── 검색 (Playwright) ──
def search_disclosures(report_nm: str, from_date: str, to_date: str,
                       title_filter: str = None, page_size: int = 100) -> list:
    """
    KIND 공시 검색.

    report_nm   : 보고서명 검색어 (예: 'ETF이익금분배신고'). 부분일치.
    from_date   : 'YYYY-MM-DD'
    to_date     : 'YYYY-MM-DD'
    title_filter: 결과 제목에 이 정규식이 맞는 것만 반환 (선택)

    Returns: [{acptno, date, corp, title}, ...]

    ⚠️ 기간을 넓게 주지 말 것 — 두 제약 모두 오류 없이 '조용히' 결과가 잘린다.
       1) 결과 100건 상한: 초과분이 잘리고, 최신순 정렬이라 오래된 것부터 사라진다.
          (실측: 2018년 한 번에 100건 / 상·하반기로 나누면 100+77=177건)
       2) 기간 3년 초과 시 0건: 5년 범위로 검색하면 오류 없이 빈 결과가 온다.
          (실측: '이익금분배' 2005~2009 → 0건, 2009년 단독 → 77건)
       → 호출 측에서 월 단위로 쪼갤 것. kind_fetch.month_chunks() 참고.
    """
    return search_disclosures_batch(report_nm, [(from_date, to_date)],
                                    title_filter, page_size)[0]


def search_disclosures_batch(report_nm: str, ranges: list,
                             title_filter: str = None, page_size: int = 100,
                             progress=None) -> list:
    """
    여러 기간을 한 번의 브라우저 세션으로 검색한다.

    ranges: [(from_date, to_date), ...]
    Returns: ranges와 같은 길이의 리스트. 각 원소는 해당 구간의 결과 목록.

    브라우저 기동이 검색 시간의 대부분(약 12초)이라, 구간이 많을 때는
    반드시 이 함수를 쓸 것. 구간당 1~3초로 줄어든다.
    """
    from playwright.sync_api import sync_playwright

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(user_agent=UA)
            page.goto(SEARCH_URL, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_selector("#reportNmTemp", timeout=30000)

            for i, (from_date, to_date) in enumerate(ranges):
                rows = _search_once(page, report_nm, from_date, to_date, page_size)
                if title_filter:
                    rx = re.compile(title_filter)
                    rows = [r for r in rows if rx.search(r["title"])]
                rows = [r for r in rows if r.get("acptno")]
                results.append(rows)
                if progress:
                    progress(i + 1, len(ranges), from_date, len(rows))
        finally:
            browser.close()
    return results


def _read_rows(page) -> list:
    """현재 결과 테이블의 행을 파싱."""
    return page.evaluate(
        """() => [...document.querySelectorAll('table.list tbody tr')].map(tr => {
            const a = [...tr.querySelectorAll('a')]
                .find(x => /openDisclsViewer/.test(x.getAttribute('onclick') || ''));
            if (!a) return null;
            const m = (a.getAttribute('onclick') || '').match(/openDisclsViewer\\('(\\d+)'/);
            const c = [...tr.cells].map(td => td.innerText.trim().replace(/\\s+/g, ' '));
            return {
                acptno: m ? m[1] : '',
                date: (c[1] || '').slice(0, 10),
                corp: c[2] || '',
                title: a.innerText.trim().replace(/\\s+/g, ' '),
            };
        }).filter(Boolean)"""
    )


def _search_once(page, report_nm: str, from_date: str, to_date: str, page_size: int,
                 max_pages: int = 20) -> list:
    """
    이미 열린 KIND 검색 페이지에서 한 구간을 조회.

    ⚠️ 한 페이지는 최대 100건이고 초과분은 잘린다. 날짜를 하루로 좁혀도
       100건을 넘는 날이 있다(예: 2018-04-26, 2019-04-26 — ETF 결산 분배가 몰림).
       그래서 날짜 분할만으로는 부족하고 페이지를 넘겨가며 모아야 한다.
    """
    page.evaluate(
        """([nm, fd, td, size]) => {
            document.getElementById('reportNmTemp').value = nm;
            const f = document.getElementById('searchForm');
            f.querySelector('[name="fromDate"]').value = fd;
            f.querySelector('[name="toDate"]').value   = td;
            const hid = f.querySelector('#currentPageSize');
            if (hid) hid.value = size;
            const sel = document.querySelector('select#currentPageSize');
            if (sel) sel.value = size;
            fnSearch();
        }""",
        [report_nm, from_date, to_date, str(page_size)],
    )
    page.wait_for_timeout(2000)

    # 페이지 크기가 반영되지 않았으면 한 번 더 요청
    if page.evaluate("document.querySelectorAll('table.list tbody tr').length") <= 15 \
            and page_size > 15:
        page.evaluate(
            """(size) => {
                const sel = document.querySelector('select#currentPageSize');
                if (sel) sel.value = size;
                const hid = document.querySelector('#searchForm #currentPageSize');
                if (hid) hid.value = size;
                if (typeof fnPageGo2 === 'function') fnPageGo2(1);
            }""",
            str(page_size),
        )
        page.wait_for_timeout(2000)

    rows = _read_rows(page)
    if len(rows) < page_size:
        return rows

    # 첫 페이지가 가득 찼으면 뒤 페이지가 더 있다 — 새 결과가 안 나올 때까지 넘긴다
    seen = {r["acptno"] for r in rows}
    for pg in range(2, max_pages + 1):
        page.evaluate("(p) => { if (typeof fnPageGo2 === 'function') fnPageGo2(p); }", pg)
        page.wait_for_timeout(2000)
        more = _read_rows(page)
        fresh = [r for r in more if r["acptno"] not in seen]
        if not fresh:
            break
        seen.update(r["acptno"] for r in fresh)
        rows.extend(fresh)
        if len(more) < page_size:
            break
    return rows


# ── 유틸 ──
def doc_to_text(html: str) -> str:
    """공시 HTML → 공백 정규화된 평문."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
