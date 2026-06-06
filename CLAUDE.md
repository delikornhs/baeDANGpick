# 배당픽 프로젝트 지침

## 사이트 정보
- URL: bae-dang-pick.vercel.app
- GitHub: delikornhs/baeDANGpick
- 배포: GitHub push → Vercel 자동 배포

---

## 월간 분석 작성 요청 시

"N월 분석 작성해줘" 요청이 오면 아래 순서로 진행한다.

### 1단계: 데이터 추출

```python
import json, sys
sys.stdout.reconfigure(encoding='utf-8')
with open('data/output/latest.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
# current=True, freq in ('월배당','월배당추정') 항목 전체 대상
# 분석 기준월: 요청한 달 (예: "6월" → ex_date startswith '2026-06')
```

추출할 데이터:
- 월배당 ETF 중 current=True인 항목
- 3개월치 분배금 추이 (당월, 전월, 전전월)
- 분배율(rate), 현재가(price)
- 3개월 이상 연속 감소 ETF

### 2단계: 분석 기준

**분배율 뒤집어보기**
- 기회 신호: 분배율 1% 이상 + 3개월 분배금 상승 또는 안정
- 주의 신호: 분배율 1% 이상 + 3개월 분배금 감소

**추세 점검**
- 3개월 이상 연속 감소 ETF만 포함
- 여러 상품이 같은 방향이면 구조적 원인 분석

**같은 듯 다른 ETF** (의미 있는 비교가 있을 때만 작성, 없으면 생략)
- 유형 ①: 같은 지수, 다른 전략 (고정/타겟/OTM 등)
- 유형 ②: 같은 지수, 다른 운용사
- 유형 ③: 같은 테마, 다른 구조
- 비교는 같은 기초자산 기반 상품끼리만 (국내/미국 혼재 금지)
- 원인 불명확하면 추측하지 말고 "확인 필요"로 명시

**주의사항**
- 이름 축약 금지 (ETF 전체 이름 사용)
- 원인 불명확한 내용은 추측하지 않음
- 문체: 합쇼체 (~입니다, ~습니다)

### 3단계: HTML 출력

관리자 페이지(admin.html) textarea에 바로 붙여넣을 수 있는 HTML로 출력한다.

**섹션 구조 및 HTML 클래스:**

```html
<!-- 이달의 요약 -->
<h2>이달의 요약</h2>
<p>한 달 전체를 한 문단으로</p>
<hr>

<!-- 분배율 뒤집어보기 -->
<h2>분배율 뒤집어보기</h2>
<p>분배율 개념 설명...</p>

<h3>✅ 분배율도 높고, 분배금도 오르고 있는 ETF</h3>
<table>
  <tr><th>ETF</th><th>분배율</th><th>3월→4월→5월</th><th>추세</th></tr>
  <tr><td>ETF 전체명</td><td>X.XX%</td><td>XXX→XXX→XXX원</td><td>3개월 연속 상승</td></tr>
</table>
<p>해석...</p>

<h3>⚠️ 분배율은 높지만, 분배금은 줄고 있는 ETF</h3>
<table>...</table>
<p>해석...</p>
<hr>

<!-- 추세 점검 -->
<h2>추세 점검</h2>
<h3>[그룹명] — N개월 연속 감소</h3>
<table>
  <tr><th>ETF</th><th>N-3월</th><th>N-2월</th><th>N-1월</th><th>당월</th><th>누적 감소</th></tr>
</table>
<p>구조적 원인 및 시사점...</p>
<hr>

<!-- 같은 듯 다른 ETF (있을 때만) -->
<h2>같은 듯 다른 ETF</h2>
<p><strong>이번 달: [비교 주제]</strong></p>
<table>
  <tr><th>ETF</th><th>전략</th><th>N-2월</th><th>N-1월</th><th>당월</th><th>전월비</th><th>분배율</th></tr>
</table>
<p>시사점...</p>
```

> ⚠️ **주의**: 본문 HTML에 `<div class="notice">` 주의사항을 포함하지 않는다.
> api/publish.js 템플릿이 자동으로 추가하므로 넣으면 두 번 출력된다.

### 4단계: 관리자 페이지 입력값 안내

HTML 출력 후 아래도 함께 안내한다:
- **제목**: 예) 2026년 6월 월배당 ETF 분배금 진단
- **날짜**: YYYY-MM-DD
- **카테고리**: 월간분석
- **요약**: 한 줄 요약 (목록 카드에 표시)

---

## 월중 현황 작성 요청 시

"N월 월중 현황 작성해줘" 요청이 오면 아래 순서로 진행한다.

### 1단계: 데이터 추출

```python
import json, sys
sys.stdout.reconfigure(encoding='utf-8')
with open('data/output/latest.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# 월중 배당 ETF 필터
mid = [d for d in data if d.get('current') == True
       and d.get('timing') == '월중'
       and d.get('freq') in ('월배당', '월배당추정')
       and d.get('ex_date','').startswith('YYYY-MM')]  # 요청한 달로 변경

def get_chg(d):
    trend = d.get('trend', [])
    if len(trend) >= 2:
        prev = trend[-2].get('dist', 0)
        curr = d.get('dist', 0)
        if prev and prev > 0:
            return round((curr - prev) / prev * 100, 1)
    return None

def t3_str(d):
    trend = d.get('trend', [])
    t3 = trend[-3:] if len(trend) >= 3 else trend
    return '→'.join([str(t.get('dist','?')) for t in t3])

# 분배율 TOP10
by_rate = sorted(mid, key=lambda x: x.get('rate',0), reverse=True)[:10]
# 분배금 TOP10
by_dist = sorted(mid, key=lambda x: x.get('dist',0), reverse=True)[:10]
# 주가/총수익률 순위 비교
valid = [d for d in mid if d.get('return_1m') is not None and d.get('total_return_1m') is not None]
by_price = sorted(valid, key=lambda x: x.get('return_1m',0), reverse=True)
by_total = sorted(valid, key=lambda x: x.get('total_return_1m',0), reverse=True)
total_rank = {d['code']: i+1 for i, d in enumerate(by_total)}
```

추출할 데이터:
- timing='월중', freq in ('월배당','월배당추정'), current=True
- 분배율 TOP10, 분배금 TOP10 (순위 포함)
- 주가 수익률 TOP10 → 총수익률 기준 순위 변화
- 전월 대비 상승/하락/동일 개수

### 2단계: HTML 출력

**섹션 구조:**

```html
<!-- 요약 -->
<h2>N월 월중 배당 ETF 분배금 확정</h2>
<p>전체 XX개 확정. 상승 XX개, 하락 XX개, 동일 XX개. 이달 전반적 흐름 한 문장.</p>
<hr>

<!-- 분배율 TOP10 -->
<h2>분배율 TOP 10</h2>
<p>분배율 특징 및 주의사항 한 줄.</p>
<table>
  <tr><th>순위</th><th>ETF</th><th>분배금</th><th>N-2월→N-1월→당월</th><th>전월비</th><th>분배율</th></tr>
  ...
</table>
<hr>

<!-- 분배금 TOP10 -->
<h2>분배금 TOP 10</h2>
<p>절대 금액 기준 특징 한 줄.</p>
<table>
  <tr><th>순위</th><th>ETF</th><th>분배금</th><th>N-2월→N-1월→당월</th><th>전월비</th><th>분배율</th></tr>
  ...
</table>
<hr>

<!-- 수익률 순위 비교 -->
<h2>분배금이 수익률 순위를 어떻게 바꾸나</h2>
<p>개념 설명.</p>
<table>
  <tr><th>주가수익률 순위</th><th>ETF</th><th>주가 수익률</th><th>총수익률</th><th>분배 기여</th><th>총수익률 순위</th></tr>
  ...
</table>
<p>순위 변화 인사이트. 분배금 영향이 큰 상품 vs 작은 상품 대비.</p>
<p>분배금의 의미 — 상승장/횡보장/하락장에 따른 역할 차이.</p>
<hr>

<!-- 이달의 체크포인트 -->
<h2>이달의 체크포인트</h2>
<h3>주목할 상품명 또는 테마</h3>
<p>해석...</p>
...
```

> ⚠️ **주의**: 본문 HTML에 `<div class="notice">` 주의사항을 포함하지 않는다.
> api/publish.js 템플릿이 자동으로 추가하므로 넣으면 두 번 출력된다.

### 3단계: 관리자 페이지 입력값 안내

- **제목**: 예) 2026년 6월 월중 배당 ETF 분배금 확정
- **날짜**: YYYY-MM-15 (월중 배당락일 기준)
- **카테고리**: 월중현황
- **요약**: 한 줄 요약

---

## 월말 현황 작성 요청 시

"N월 월말 현황 작성해줘" 요청이 오면 아래 순서로 진행한다.

### 1단계: 데이터 추출

```python
import json, sys
sys.stdout.reconfigure(encoding='utf-8')
with open('data/output/latest.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# 월말 배당 ETF 필터
eom = [d for d in data if d.get('current') == True
       and d.get('timing') == '월말'
       and d.get('freq') in ('월배당', '월배당추정')
       and d.get('ex_date','').startswith('YYYY-MM')]  # 요청한 달로 변경

def get_chg(d):
    trend = d.get('trend', [])
    if len(trend) >= 2:
        prev = trend[-2].get('dist', 0)
        curr = d.get('dist', 0)
        if prev and prev > 0:
            return round((curr - prev) / prev * 100, 1)
    return None

def t3_str(d):
    trend = d.get('trend', [])
    t3 = trend[-3:] if len(trend) >= 3 else trend
    return '→'.join([str(t.get('dist','?')) for t in t3])

# 분배율 TOP10
by_rate = sorted(eom, key=lambda x: x.get('rate',0), reverse=True)[:10]
# 분배금 TOP10
by_dist = sorted(eom, key=lambda x: x.get('dist',0), reverse=True)[:10]
# 주가/총수익률 순위 비교
valid = [d for d in eom if d.get('return_1m') is not None and d.get('total_return_1m') is not None]
by_price = sorted(valid, key=lambda x: x.get('return_1m',0), reverse=True)
by_total = sorted(valid, key=lambda x: x.get('total_return_1m',0), reverse=True)
total_rank = {d['code']: i+1 for i, d in enumerate(by_total)}
```

추출할 데이터:
- timing='월말', freq in ('월배당','월배당추정'), current=True
- 분배율 TOP10, 분배금 TOP10 (순위 포함)
- 주가 수익률 TOP10 → 총수익률 기준 순위 변화
- 전월 대비 상승/하락/동일 개수

### 2단계: HTML 출력

**섹션 구조 (월중과 동일):**

```html
<!-- 요약 -->
<h2>N월 월말 배당 ETF 분배금 확정</h2>
<p>전체 XX개 확정. 상승 XX개, 하락 XX개, 동일 XX개. 이달 전반적 흐름 한 문장.</p>
<hr>

<!-- 분배율 TOP10 -->
<h2>분배율 TOP 10</h2>
<p>분배율 특징 및 주의사항 한 줄.</p>
<table>
  <tr><th>순위</th><th>ETF</th><th>분배금</th><th>N-2월→N-1월→당월</th><th>전월비</th><th>분배율</th></tr>
  ...
</table>
<hr>

<!-- 분배금 TOP10 -->
<h2>분배금 TOP 10</h2>
<p>절대 금액 기준 특징 한 줄.</p>
<table>
  <tr><th>순위</th><th>ETF</th><th>분배금</th><th>N-2월→N-1월→당월</th><th>전월비</th><th>분배율</th></tr>
  ...
</table>
<hr>

<!-- 수익률 순위 비교 -->
<h2>분배금이 수익률 순위를 어떻게 바꾸나</h2>
<p>개념 설명.</p>
<table>
  <tr><th>주가수익률 순위</th><th>ETF</th><th>주가 수익률</th><th>총수익률</th><th>분배 기여</th><th>총수익률 순위</th></tr>
  ...
</table>
<p>순위 변화 인사이트. 분배금 영향이 큰 상품 vs 작은 상품 대비.</p>
<p>분배금의 의미 — 상승장/횡보장/하락장에 따른 역할 차이.</p>
<hr>

<!-- 이달의 체크포인트 -->
<h2>이달의 체크포인트</h2>
<h3>주목할 상품명 또는 테마</h3>
<p>해석...</p>
...
```

> ⚠️ **주의**: 본문 HTML에 `<div class="notice">` 주의사항을 포함하지 않는다.
> api/publish.js 템플릿이 자동으로 추가하므로 넣으면 두 번 출력된다.

### 3단계: 관리자 페이지 입력값 안내

- **제목**: 예) 2026년 6월 월말 배당 ETF 분배금 확정
- **날짜**: YYYY-MM-DD (월말 배당락일 기준)
- **카테고리**: 월말현황
- **요약**: 한 줄 요약

---

## 비정기 분석 작성 시

"[주제] 분석해줘" 또는 "[주제] 글 작성해줘" 요청이 오면:
- 동일한 HTML 출력 방식 사용
- 섹션 구조는 내용에 맞게 자유롭게
- 주의사항 문구는 동일하게 포함

---

## 사이트 주요 데이터 파일

- `data/output/latest.json` — 현재 ETF 분배금 데이터 (분배율, 분배금, 추이 등)
- `data/output/etf_data.js` — ETF 전체 데이터 (수익률 포함)
- `insight/posts.json` — 인사이트 글 목록
- `insight/posts/` — 개별 글 파일

## 사이트 주요 페이지

- `index.html` — 메인
- `insight.html` — 인사이트 목록
- `admin.html` — 관리자 작성 페이지 (비밀번호 보호)
- `api/publish.js` — 게시 서버리스 함수
- `ranking.html` — 랭킹
- `portfolio.html` — MY ETF
