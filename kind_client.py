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
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(user_agent=UA)
            page.goto(SEARCH_URL, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_selector("#reportNmTemp", timeout=30000)

            # 결과 개수 select를 먼저 늘려둔다 (fnSearch가 이 값을 읽어감)
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
            page.wait_for_timeout(2500)

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
                page.wait_for_timeout(2500)

            rows = page.evaluate(
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
        finally:
            browser.close()

    if title_filter:
        rx = re.compile(title_filter)
        rows = [r for r in rows if rx.search(r["title"])]
    return [r for r in rows if r.get("acptno")]


# ── 유틸 ──
def doc_to_text(html: str) -> str:
    """공시 HTML → 공백 정규화된 평문."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
