# 배당픽 프로젝트 지침

## 사이트 정보
- URL: baedangetf.com
- GitHub: delikornhs/baeDANGpick
- 배포: GitHub push → Vercel 자동 배포

---

## 분배금 안정성 지표 계산 기준

**적용 파일:** `etf_data_processor.py`, `etf.html`, `compare.html`

### 집계 기준 (통일)
| 구분 | 기준 |
|---|---|
| 월배당/월배당추정 | 최근 **6건** (개수 기준) |
| 분기배당이상 | 최근 **4건** (개수 기준) |

- 분배금 히스토리 섹션: `trend.slice(-6)` / `trend.slice(-4)` (개수 기준)
- 분배금 안정성 섹션: 동일한 개수 기준으로 통일
- 그룹평균(peer): 캐시(`x.stab`) 사용하지 않고 동일 개수 기준으로 직접 계산

### 수정 이유
기존에는 안정성 계산에 날짜 기준(182일)을 사용했는데, 배당락일이 경계에 걸리면 6개월 안에 7건 또는 5건이 포함되어 히스토리 섹션(항상 6건)과 월평균 값이 달라지는 문제가 있었다. (예: TIGER 배당커버드콜액티브 — 히스토리 425원 vs 안정성 373원)

또한 그룹평균 계산 시 peer ETF의 캐시값(`x.stab.avgMonthlyRate/Dist`)을 우선 사용하던 방식은 캐시 생성 시점에 따라 내 값과 기준이 달라질 수 있어 직접 계산 방식으로 변경했다.

### ⚠️ 프로세서 기본 경로(XLS)에서도 안정성 지표 계산
기존 `etf_data_processor.py`의 기본 실행 경로(XLS 파일 처리)에서는 `calc_stability_metrics`가 호출되지 않았고, `PRESERVE_FIELDS`로 이전 `latest.json`의 안정성 값이 그대로 유지되었다. 이 때문에 count 기준으로 수정 후 프로세서를 재실행해도 `avg_monthly_dist` 등이 업데이트되지 않았다.

**수정 내용 (`etf_data_processor.py`):**
- 기본 경로 5단계(분배율 계산) 직후에 안정성 지표 계산 블록 추가 (step 6)
- `PRESERVE_FIELDS`에서 안정성 관련 필드 제거 (항상 새로 계산하도록)
  - 제거된 필드: `stab_score`, `stab_variation`, `stab_trend`, `trend_change_pct`, `stab_level`, `stab_level_dist`, `annual_dist`, `annual_rate`, `avg_monthly_dist`, `avg_monthly_rate`, `peer_group`, `group_avg_rate`, `group_avg_dist`

---

## ⚠️ etf.html JS 수정 시 주의사항

`render()` 함수 안에서 `const`/`let`을 `if` 블록 내부에 선언하면, 블록 밖 코드에서 참조 시 `ReferenceError`가 발생해 **ETF 상세 페이지 전체가 렌더링되지 않는다.**

- 여러 섹션에서 공통으로 쓰이는 변수는 반드시 함수 최상단(블록 밖)에 선언
- 커밋 전, 새로 선언한 변수가 참조되는 모든 위치가 같은 스코프 안에 있는지 확인

---

## ⚠️ e.ex 필드의 실제 의미 = 배당락일이 아닌 기준일

`latest.json`/`etf_data.js`의 `ex_date`(JS에서는 `e.ex`) 필드는 이름과 달리 **배당락일이 아니라 기준일**이다.

원본 XLS(KIND ETF이익금분배신고) 컬럼명이 "투자신탁 분배금 지급**기준일**"이며, `etf_data_processor.py`가 이 값을 그대로 `ex_date`라는 필드명에 저장한다.

> 2026-07-15 오류 사례: `etf.html` 상세페이지가 `e.ex`를 배당락일로 취급해 표시하고 그 하루 전을 최종매수일로 계산 → 최종매수일·배당락일이 실제보다 하루씩 밀려 표시됨. 메인 달력(`CONFIRMED_SCHEDULE`)은 사람이 공시 원문을 보고 직접 입력하므로 정확했고, 이 차이로 발견됨.

**올바른 역산 순서** (etf.html에 적용됨):
```js
const record = e.ex;                // 기준일 (그대로)
const ex     = prevBizDay(record);  // 배당락일 = 기준일 1영업일 전
const lb     = prevBizDay(ex);      // 최종매수일 = 배당락일 1영업일 전
```

**⚠️ 남은 한계 — 공휴일 미반영**: `prevBizDay()`는 토·일요일만 건너뛰고 설날·추석·대체공휴일 등 한국 공휴일은 반영하지 못한다. 기준일 근처에 공휴일이 끼는 달에는 위 역산 결과가 실제 공시(`CONFIRMED_SCHEDULE`)와 다시 어긋날 수 있다.

- 새 달 데이터 반영 후에는 ETF 상세페이지 하나를 열어 "이번달 분배 일정" 박스 값이 그 달 `CONFIRMED_SCHEDULE`(메인 달력)의 최종매수·배당락·기준일과 일치하는지 확인할 것
- 어긋나면 해당 달에 공휴일이 끼어 있는지부터 의심할 것

---

## ⚠️ 네이버 fchart API로 일별 종가 조회 시 주의사항

`fchart.stock.naver.com/sise.nhn`에 `count` 파라미터로 요청하면 **서버 자체에 최근 3000건 하드캡**이 있다. `count`를 10000처럼 크게 줘도 응답은 항상 최근 3000건까지만 온다 (우리 코드의 제한이 아니라 API 서버 자체의 제한임을 실제 호출로 확인).

> 2026-07-15 오류 사례: 상장 후 3000영업일(약 12년)이 넘은 103개 종목의 "상장이후 수익률"이 실제 상장일이 아니라 그로부터 11~12년 뒤 시점의 가격을 기준으로 계산되고 있었음. (예: KODEX 200 — 2002-10-14 상장인데 응답 시작일이 2014-04-28이 되어 상장이후 수익률이 약 435%로 표시됨 → 정정 후 2055.95%)

**해결 (`etf_data_processor.py`의 `fetch_daily_price_history()`에 적용됨):** `count` 대신 `fchart.stock.naver.com/siseJson.nhn`에 `startTime`(상장일, YYYYMMDD)·`endTime`(오늘, YYYYMMDD)을 직접 지정하면 캡 없이 상장일부터 전체 구간을 한 번의 요청으로 받아온다.

- 응답 포맷: `["YYYYMMDD", 시가, 고가, 저가, 종가, 거래량, ...]` — 종가는 date 다음 4번째 숫자 필드
- 인코딩은 UTF-8 (구 `sise.nhn`은 EUC-KR — 새 엔드포인트로 바꿀 때 함께 변경 필요)
- 조회 결과는 `data/output/price_history/{code}.json`에 종목별로 영구 저장됨 (`--prices-only` 실행 시마다 갱신). 종가 이력이 필요한 작업은 재조회 없이 이 파일을 바로 읽을 것
- `days_since_listed()` 함수는 이 수정으로 불필요해져 제거됨 — 유사한 "영업일 수 계산 후 count로 조회" 패턴을 다시 만들지 않도록 주의

---

## ⚠️ 데일리 업데이트 워크플로우에 새 출력 파일 추가 시 `git add`도 함께 수정

`etf_data_processor.py`가 새로 쓰는 출력 파일/폴더를 추가하면, **반드시 `.github/workflows/update-prices.yml`의 `git add` 목록에도 그 경로를 추가**해야 한다. 안 그러면 워크플로우가 커밋 후 `git pull --rebase` 단계에서 죽는다.

> 2026-07-23 오류 사례: "종가 이력 영구 저장"(price_history) 기능을 추가하면서 프로세서가 `--prices-only` 실행마다 `data/output/price_history/{code}.json` 915개를 새로 쓰게 됐는데, `update-prices.yml`의 `git add`에는 이 폴더가 빠져 있었다. 그 결과 매 실행마다 이 파일들이 **스테이징되지 않은 채로 남아**, 커밋 직후의 `git pull --rebase origin master`가 `error: cannot pull with rebase: You have unstaged changes`로 실패했다. 7/23·7/24 데일리 업데이트가 연속 실패해 사이트 종가가 7/22에 멈춰 있었음. (기능 추가 자체는 성공했으나 워크플로우 스테이징 목록을 함께 갱신하지 않은 게 원인)

**해결 (`update-prices.yml`에 적용됨):** 커밋 스텝의 `git add`와 rebase 충돌 복구 블록(`git checkout --ours` / `git add`) 양쪽에 `data/output/price_history`를 추가했다.

- 원인 진단은 `mcp__github__get_job_logs`로 실패 run의 로그를 직접 확인 (스텝 9 "Commit and push if changed"에서 exit 128)
- 수정 후 `mcp__github__actions_run_trigger`로 수동 트리거해 검증 — 단, **수동 트리거(workflow_dispatch)는 메타 조회를 강제로 돌려서 완주에 ~1시간 걸린다.** 매일 자동 스케줄 실행은 월요일 빼고 메타를 건너뛰므로 훨씬 빠름
- **트레이드오프**: 이 수정으로 데일리 커밋마다 price_history 900여 개 파일 변경이 함께 들어간다(매일 새 종가가 붙으므로). git 동작에는 문제없으나 저장소가 매일 그만큼 커진다. 저장소 비대화가 문제되면 나중에 price_history를 별도 브랜치/저장 방식으로 분리하는 것을 고려

---

## ⚠️ update-prices.yml 리베이스 충돌 시 --ours/--theirs를 반대로 써서 방금 계산한 수익률이 버려짐

리베이스(`git rebase`) 도중에는 `--ours`/`--theirs`의 의미가 평소(merge)와 반대로 뒤집힌다 — `--ours`는 리베이스 대상(origin/master, 구버전), `--theirs`는 지금 재생 중인 내 커밋(방금 만든 새 데이터)이다. `update-prices.yml`은 (위 2026-07-23 수정 때도) 계속 `--ours`를 쓰고 있었는데, 이는 충돌 시 **origin/master의 구버전을 채택**하는 것과 같아서 주석("데이터 파일은 워크플로우(최신 가격) 버전 우선")의 의도와 정반대로 동작하고 있었다.

> 2026-07-29 오류 사례: 코스피가 크게 하락한 날, ETF 상세페이지 "1주 수익률"이 이상하게 플러스로 나온다는 제보로 발견. `kind-watch.yml`(분배금 공시 처리 — 수익률 필드는 재계산 없이 보존만 함)이 먼저 push했고, 뒤이어 돌린 `update-prices.yml`(`--prices-only`, 수익률 재계산)이 그 위에서 리베이스 충돌을 겪었다. `--ours`를 쓴 탓에 방금 계산한 정확한 값(RISE 200위클리커버드콜 ret1w -16.15%)이 버려지고, `kind-watch.yml`이 보존해뒀던 며칠 전 stale한 값(+2.04%)이 그대로 사이트에 남았다. `kind-watch.yml` 자신은 처음부터 `--theirs`를 올바르게 쓰고 있어 문제없었다.

**해결 (`update-prices.yml`에 적용됨):** 커밋 스텝(`data/output/*` 파일)과 포스트 커밋 스텝(`posts/`) 두 곳 모두 `git checkout --ours` → `git checkout --theirs`로 수정.

- 이 버그는 두 워크플로우가 **비슷한 시간에 겹쳐 실행돼 리베이스 충돌이 날 때만** 증상이 나타난다. 평소처럼 순차 실행되면 충돌 자체가 없어 드러나지 않으므로, 2026-07-23 이후 계속 잠복해 있었을 가능성이 있다.
- 진단 순서: "1주 수익률이 이상하다"는 지적 → 해당 종목 `price_history/{code}.json`으로 직접 검산해 실제로는 마이너스여야 함을 확인 → `mcp__github__get_job_logs`로 문제 발생 실행의 커밋 스텝 로그를 읽어 `Auto-merging ... CONFLICT` → `checkout --ours` 흐름을 직접 확인
- 수정 후 검증: 워크플로우 재트리거 → `etf_data.js`에서 `ret1w`가 실제로 -16.15%로 바뀐 것을 직접 확인
- `send-data-newsletter.yml`/`send-schedule-newsletter.yml`도 `archive.json` 충돌 처리에 `--ours`를 쓰고 있다 — 다만 이 파일은 "이미 발송한 기록"을 다루므로 의미가 다를 수 있어 이번에는 건드리지 않았다. 비슷한 증상(발송 여부가 꼬임)이 생기면 함께 점검할 것

---

## ⚠️ 비거래일(주말·공휴일)에 프로세서를 돌리면 등락률이 전 종목 0%가 된다

`fetch_naver_prices()`가 돌려주는 `price_date`는 **실행 당일 날짜일 뿐**이고 거래일인지 확인하지 않는다. 비거래일에 실행하면 네이버가 주는 값은 직전 거래일 종가인데, 코드는 그 날짜를 "오늘"로 취급한다. 이 때문에 두 가지가 동시에 틀어졌다.

> 2026-08-03 오류 사례: 메인 ETF 카드의 "최근 종가" 옆 등락률이 전부 0%로 표시된다는 제보로 발견.
> 7/31(금) 데일리 실행(`dfa0929`)까지는 1,009건 중 905건이 정상값이었는데, **8/1(토)에 돌린 실행(`916c886`)이 921건 전부를 0.0으로 덮어썼다.**
> `chg_pct`가 `PRESERVE_FIELDS`에 있어 다음 거래일 실행 전까지 0%가 그대로 남는다.

**① 전일 대비 등락률이 자기 자신과 비교됨** — 기존 코드는 `price_date` 이전의 가장 최근 종가를 "전일 종가"로 잡았다. 비거래일에는 `daily`의 마지막 항목(= 현재가 그 자체)이 `price_date`보다 앞서므로 **자기 자신이 전일 종가로 선택**되어 `(P-P)/P = 0`이 된다.

**해결:** 탐색 중 만난 종가가 현재가와 같으면 한 칸 더 앞의 거래일을 전일로 잡는다. 장중 실행(현재가가 아직 `daily`에 없음)·장마감 후 정상 실행 경로는 결과가 그대로라 회귀 없음.

**② 종가 기준일 라벨이 비거래일 날짜로 표시됨** — 히어로 영역의 `종가 {PRICE_DATE}`가 "종가 2026-08-01"(토요일)로 나왔다.

**해결:** `resolve_price_date()` 추가. 저장된 종가 이력과 현재가를 대조해 실제 기준일을 판별한다.
- 최근 거래일 이력 ≥ `price_date` → 당일 종가가 이미 있음 = 거래일 → 그대로
- 현재가가 이력 마지막 종가와 다른 종목이 10% 넘음 → 장중 실행 = 오늘 시세가 맞음 → 그대로
- 그 외(거의 전부 stale) → 이력의 최근 거래일로 교체
- `price=0`(조회 실패)·상장폐지 종목은 판별 근거에서 제외. **이걸 빼먹으면 stale 비율이 89%로 나와 보정이 안 걸린다**
- `--prices-only` 경로는 루프에서 모은 `daily`를, 기본(XLS) 경로는 `sample_last_closes()`로 `price_history/` 파일 100개를 읽어 판별

- 평일 스케줄(`cron: 30 8 * * 1-5`, 17:30 KST 장 마감 후)은 당일 종가가 이미 이력에 있어 원래도 정상이었다. **문제는 주말 수동 트리거와 평일 공휴일** — cron `1-5`는 설날·추석·대체공휴일을 걸러내지 못한다
- `price_date`는 `WEEK_START`/`WEEK_END` 계산에도 쓰이지만, 보정 전후 결과가 같아 영향 없음 (토요일 → 직전 금요일로 수렴하므로)

---

## ⚠️ git 커밋 주의사항

코드 수정(HTML, JS 등)만 커밋할 때 반드시 `git status`로 staged 파일을 먼저 확인한다.
`git add [특정파일]`을 해도 이미 staged된 파일이 있으면 함께 커밋되어 데이터가 덮어씌워질 수 있다.

```bash
# 항상 커밋 전 확인
git status

# 특정 파일만 명시적으로 추가
git add ranking.html   # 데이터 파일(etf_data.js, latest.json 등)은 절대 포함하지 않도록 주의
git commit -m "..."
```

데이터 파일(`data/output/etf_data.js`, `data/output/latest.json`)은 데이터 업데이트 작업 외에는 커밋하지 않는다.

---

## 새 PC 최초 세팅

```bash
# 1. 코드 클론
git clone https://github.com/delikornhs/baeDANGpick
cd baeDANGpick

# 2. 파이썬 패키지 설치
pip install -r requirements.txt

# 3. Playwright 설치 (쇼츠 이미지 캡처용)
python -m playwright install chromium

# 4. data/raw/ 폴더를 기존 PC에서 복사
#    (원본 XLS 파일들 — GitHub에 올라가지 않으므로 직접 복사 필요)
```

이후 매달 새 XLS 파일은 `data/raw/YYYY년 MM월/` 폴더에 넣고 프로세서 실행.
코드 변경사항 동기화: `git pull`

---

## 분배금 일정 업데이트 요청 시

"N월 [월중/월말] 분배 일정 업데이트해줘" 요청이 오면 아래 순서로 진행한다.
날짜를 직접 알려주면 그대로 쓰고, 없으면 0단계로 알아낸다.

> ℹ️ **일정 발견은 자동, 달력 반영은 수동이다.** `kind-watch.yml`이 평일 18:30에
> `kind_schedule.py`를 돌려 `index.html`의 `CONFIRMED_SCHEDULE`과 대조하고,
> 달력에 없는 정규 회차를 찾으면 **회차당 한 번** 이슈를 만든다
> (제목: `📅 분배 일정 확인 — 달력 미반영 [sched-기준일]`).
> 달력 자동 수정은 하지 않는다 — 공휴일 오차 때문에 사람이 보는 단계를 남겨둔 것.

### 0단계: 일정 자동 파악 (날짜를 못 받은 경우)

```bash
python -X utf8 kind_schedule.py
```

- KIND '설정/환매접수 일시중지 안내' 공시의 **중지기간 종료일 = 최종매수일**
  (2026-03~07 8개 회차 전부 실제와 일치 확인). 배당락일 = +1영업일, 기준일 = +2영업일
- 이 공시는 최종매수일 **5~9일 전**에 올라오므로 미리 알 수 있다
- **정규/비정기 판정은 기준일 패턴으로 한다** — 기준일이 그 달 15일(주말이면 직전 평일)
  또는 마지막 영업일에 정확히 붙으면 정규 회차. 그 외는 비정기라 달력에 넣지 않는다.
  명부확정일은 운용사끼리 공유하므로 **공시가 한 건만 올라와도 판정된다.**
  > 2026-08-07 변경: 종전에는 종목수 15 이상을 정규로 봤는데 양방향으로 틀렸다.
  > 첫 공시 한 건만 올라온 시점에는 정규인데도 놓쳤고(거짓 음성), 기준일 2026-08-03
  > 회차는 22종목이라 정규로 잡혔지만 15일도 말일도 아닌 비정기였다(거짓 양성).
  > 종목수는 "몇 개 운용사가 냈나"일 뿐이라 회차 성격의 신호가 아니다.
- 종목수는 회차가 진행되며 늘어난다. **날짜는 종목수와 무관한 확정값**이므로 기다릴 필요 없다
- ⚠️ 배당락일·기준일은 주말만 반영한 계산값 — 공휴일이 끼면 하루씩 밀릴 수 있으니,
  분배금 공시가 나오면 실제 기준일과 대조해 확정할 것
- 같은 이유로 공휴일이 15일·말일에 걸리면 위 판정도 어긋난다. 패턴에 안 맞는데
  규모가 큰(40종목 이상) 회차는 **'확인필요'로 따로 출력**되므로 원문을 확인할 것

### 1단계: index.html CONFIRMED_SCHEDULE 수정

`index.html`의 `CONFIRMED_SCHEDULE` 배열에서 **해당 회차(월중 또는 월말) 3줄만** 교체한다.

> ⚠️ **배열 전체를 갈아끼우지 말 것.** 월중·월말은 서로 독립된 회차라 둘 다 배열에 남아 있어야 한다.
> 월말만 넣고 월중을 지우면 달력에서 **월중 기준일 라벨이 사라진다.**
> (최종매수·배당락·지급일은 ETF 데이터에서도 도출되어 남지만, 기준일 라벨은 이 배열에만 있음)

```js
const CONFIRMED_SCHEDULE = [
  // 월중 회차
  {date:'YYYY-MM-DD', type:'buy',    label:'최종매수',     ex:'배당락일'},
  {date:'YYYY-MM-DD', type:'ex',     label:'배당락',       ex:'배당락일'},
  {date:'YYYY-MM-DD', type:'record', label:'기준일(월중)', ex:'배당락일'},
  // 월말 회차
  {date:'YYYY-MM-DD', type:'buy',    label:'최종매수',     ex:'배당락일'},
  {date:'YYYY-MM-DD', type:'ex',     label:'배당락',       ex:'배당락일'},
  {date:'YYYY-MM-DD', type:'record', label:'기준일(월말)', ex:'배당락일'},
];
```

- `date`: 각 이벤트 날짜 (최종매수일 / 배당락일 / 기준일)
- `ex`: 같은 회차 3항목 모두 그 회차의 배당락일로 동일하게 설정
- 달력은 현재 월만 표시하므로, 지난달 회차는 자연히 안 보인다 (남겨둬도 무방)

### 2단계: git push

```bash
git add index.html
git commit -m "chore: N월 [월중/월말] 배당 일정 업데이트"
git push
```

→ Vercel 자동 배포로 달력에 즉시 반영됨

### 3단계: 뉴스레터 발송

**⚠️ 반드시 사용자 승인을 받은 뒤 발송한다. 자동 발송 금지.**

이 환경에서는 `gh` CLI가 없으므로 Python urllib로 GitHub API를 직접 호출한다.
토큰은 git credential manager에서 자동으로 가져온다.

```python
import json, urllib.request, subprocess

token = subprocess.check_output(
    'echo "protocol=https\\nhost=github.com" | git credential fill',
    shell=True, text=True
).strip().split("password=")[1]

payload = json.dumps({
    "ref": "master",
    "inputs": {
        "timing": "월중",        # 또는 "월말"
        "last_buy": "YYYY-MM-DD",
        "ex_date":  "YYYY-MM-DD",
        "record":   "YYYY-MM-DD"
    }
}).encode("utf-8")

req = urllib.request.Request(
    "https://api.github.com/repos/delikornhs/baeDANGpick/actions/workflows/send-schedule-newsletter.yml/dispatches",
    data=payload,
    headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json"
    },
    method="POST"
)
try:
    with urllib.request.urlopen(req) as r:
        print(f"✅ 뉴스레터 발송 완료 (HTTP {r.status})")
except urllib.error.HTTPError as e:
    print(f"❌ 실패 {e.code}: {e.read().decode()}")
```

- 응답 HTTP 204 = 성공
- **주의: 재시도 금지** — 204가 와도 한 번만 호출할 것. 중복 발송됨

### 4단계: 네이버 블로그 글

CLAUDE.md의 **양식 ①** (일정 안내) 참조해서 작성

---

## 분배금 데이터 업데이트 요청 시

"N월 [월중/월말] 분배금 업데이트해줘" 요청이 오면 아래 순서로 진행한다.
(사용자가 직접 XLS를 받아두고 "올렸어"라고 해도 동일하게 동작한다 — 1단계에서 건너뛴다)

> ℹ️ **평일 18:30에는 `kind-watch.yml`이 1~4단계를 자동으로 수행한다.**
> 즉 이미 반영이 끝나 있을 수 있으므로, 먼저 `git pull` 후 `latest.json`의 기준일을 확인할 것.
> 이미 반영됐다면 남은 일은 **5단계 뉴스레터 발송(수동)** 뿐이다.

### 1단계: KIND에서 분배금 공시 자동 수집

```bash
python -X utf8 kind_fetch.py
```

- 기본 범위는 **지난달 1일 ~ 오늘**. 월중·월말·비정기가 한 번에 다 걸린다.
- 이미 받은 파일은 건너뛰므로 여러 번 실행해도 안전하다.
- 특정 월만: `--month 2026-07` / 과거 수집: `--from 2026-01 --to 2026-06` / 확인만: `--dry-run`
- 실행 후 출력되는 **기준일 분포**로 월중·월말·비정기가 뭐가 들어왔는지 확인해 사용자에게 보고한다.

> ⚠️ 파일명은 KIND가 주는 형식 그대로 저장된다. 프로세서가 파일명에서 공시일(`notice_date`)을
> 추출해 분배율 계산에 쓰므로 **파일명을 바꾸지 말 것.**

### 2단계: 데이터 프로세서 실행

```bash
python -X utf8 etf_data_processor.py
```

→ `data/output/latest.json`, `history.json`, `etf_data.js` 자동 생성

- 인자 없이 실행하면 최근 월중·월말 날짜를 각각 알아서 잡는다. 평소엔 인자를 붙이지 않는다.
- 월중만 업데이트한 시점이면 지난달 월말 데이터가 그대로 남아 있는 것이 정상이다.
- 비정기 ETF는 `timing`이 비고 `current=False`로 처리되는 것이 정상 (메인 달력엔 안 나오고
  상세페이지·랭킹에만 반영됨)

### 3단계: 데이터 검증

```bash
python -X utf8 kind_verify.py
```

종목 수·분배금·지급일·분배율·직전 대비 급감 여부를 확인한다. 통과(종료코드 0)해야 반영한다.

> ℹ️ `PRICE_DATE` / `MID_NOTICE_DATE` / `END_NOTICE_DATE` 상수는 **손댈 필요 없다.**
> 프로세서가 `current` 항목의 `notice_date`에서 자동 산출해 `etf_data.js`에 넣고,
> `inject_html()`이 `index.html`에 반영한다. (과거 문서에는 수동 수정하라고 돼 있었으나 불필요)

### 4단계: git push

```bash
git add data/raw data/output/latest.json data/output/history.json data/output/etf_data.js index.html
git commit -m "data: N월 [월중/월말] 분배금 데이터 업데이트"
git push
```

- `data/raw`(KIND 원본 XLS)도 함께 커밋한다 (2026-07부터 저장소에 포함)

**⚠️ push 실패(리베이스 충돌) 시 주의:**
```bash
git pull origin master --rebase
# 충돌 발생 시 data/output 파일은 --ours가 아닌 --theirs 사용
# (리베이스 도중 --ours = origin/master의 구버전, --theirs = 내가 생성한 새 데이터)
git checkout --theirs data/output/latest.json data/output/etf_data.js
git add data/output/latest.json data/output/etf_data.js
git rebase --continue
git push
```
- 리베이스 후에도 `latest.json`의 `ex_date`가 업데이트한 달 데이터인지 반드시 확인 후 뉴스레터 발송

### 5단계: 뉴스레터 발송

**⚠️ 반드시 사용자 승인을 받은 뒤 발송한다. 자동 발송 금지.**

> 2026-07-26 변경: `update-prices.yml`에 있던 **데이터 뉴스레터 자동 발송 단계를 제거**했다.
> 그 전까지는 분배금 필드가 바뀌면 매일 17:30 워크플로가 뉴스레터를 자동 발송했다.
> 이제 발송은 아래 수동 트리거만으로 이뤄지므로, **직접 트리거하지 않으면 나가지 않는다.**

**⚠️ 발송 전 반드시 확인 (3가지 모두 통과해야 발송)**

> 2026-06-26 오류 사례: `history.json`만 먼저 push하고 뉴스레터 워크플로우를 트리거했더니,
> `latest.json`이 15분 뒤에 커밋되어 5월 데이터(pay_date 6월)가 그대로 발송됨.
> **반드시 `latest.json` push 완료 후 트리거할 것.**

```bash
python -X utf8 -c "
import json
from datetime import datetime

d = json.load(open('data/output/latest.json', encoding='utf-8'))
timing = '월말'  # 또는 '월중'
target_ym = '2026-06'  # 업데이트한 달로 변경

eom = [x for x in d if x.get('timing')==timing and x.get('current')]
if not eom:
    print('❌ current=True 항목 없음')
else:
    sample = eom[0]
    ex = sample.get('ex_date', '')
    pay = sample.get('pay_date', '')
    ex_ym = ex[:7] if ex else ''
    pay_m = int(pay[5:7]) if pay else 0
    ex_m = int(ex[5:7]) if ex else 0

    print(f'ex_date: {ex}  pay_date: {pay}')

    # 검증 1: ex_date가 업데이트한 달인지
    if ex_ym != target_ym:
        print(f'❌ ex_date가 {target_ym}이 아님 → latest.json이 이전 달 데이터일 가능성')
    else:
        print(f'✅ ex_date 월 확인: {ex_ym}')

    # 검증 2: pay_date가 ex_date보다 나중인지 (지급일은 배당락 이후)
    if pay_m <= ex_m:
        print(f'❌ pay_date({pay})가 ex_date({ex})와 같은 달 이하 → 이전 달 데이터 혼입 의심')
    else:
        print(f'✅ pay_date 월 확인: {pay}')

    # 검증 3: current=True 항목 수가 정상 범위인지
    print(f'✅ current=True 항목 수: {len(eom)}개')
    if len(eom) < 50:
        print(f'⚠️ 항목 수가 너무 적음 — 필터링 이상 가능성')
"
```

이 환경에서는 `gh` CLI가 없으므로 Python urllib로 GitHub API를 직접 호출한다.

```python
import json, urllib.request, subprocess

token = subprocess.check_output(
    'echo "protocol=https\\nhost=github.com" | git credential fill',
    shell=True, text=True
).strip().split("password=")[1]

payload = json.dumps({
    "ref": "master",
    "inputs": {"timing": "월중"}   # 또는 "월말"
}).encode("utf-8")

req = urllib.request.Request(
    "https://api.github.com/repos/delikornhs/baeDANGpick/actions/workflows/send-data-newsletter.yml/dispatches",
    data=payload,
    headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json"
    },
    method="POST"
)
try:
    with urllib.request.urlopen(req) as r:
        print(f"✅ 뉴스레터 발송 완료 (HTTP {r.status})")
except urllib.error.HTTPError as e:
    print(f"❌ 실패 {e.code}: {e.read().decode()}")
```

- 응답 HTTP 204 = 성공
- **주의: 재시도 금지** — 204가 와도 한 번만 호출할 것. 중복 발송됨

### 6단계: 콘텐츠 작성 전 데이터 검증

콘텐츠 작성 전 반드시 아래 코드로 분배율 TOP 10을 뽑아 사용자에게 보여주고, 확인을 받은 후 진행한다.

```python
import json, sys
sys.stdout.reconfigure(encoding='utf-8')
with open('data/output/latest.json', encoding='utf-8') as f:
    data = json.load(f)

timing = '월말'  # 또는 '월중'
ym = 'YYYY-MM'  # 해당 월로 변경

target = [d for d in data if d.get('current') and d.get('timing') == timing
          and d.get('freq') in ('월배당','월배당추정')
          and d.get('ex_date','').startswith(ym)]
by_rate = sorted(target, key=lambda x: x.get('rate',0), reverse=True)

print(f'전체: {len(target)}개')
for i, d in enumerate(by_rate[:10], 1):
    trend = d.get('trend', [])
    prev = trend[-2].get('dist',0) if len(trend)>=2 else 0
    chg = round((d['dist']-prev)/prev*100,1) if prev else 0
    chg_s = ('+' if chg>0 else '')+str(chg)+'%' if chg else '-'
    print(f"{i}위 {d['name']} | {d['dist']}원 | {chg_s} | {d['rate']}%")
```

사용자가 순위를 확인하고 이상 없으면 콘텐츠 작성 진행.

### 7단계: 콘텐츠 작성 여부 확인

6단계까지 완료 후 반드시 아래 질문을 한다:

> "데이터 업데이트 완료됐습니다. 콘텐츠 작성도 진행할까요?"

콘텐츠 작성은 별도 요청 시에만 진행한다. 순서는 아래와 같다:
1. 네이버 블로그 — 분배금 확정 공지 (양식 ②)
2. 배당픽 인사이트 — 월중/월말 현황 글
3. 네이버 블로그 — 현황 점검 (양식 ③)

---

## 월간 분석 작성 요청 시

"N월 분석 작성해줘" 요청이 오면 아래 순서로 진행한다.

### ⚠️ 월중+월말 전체 대상임을 반드시 확인

월간 분석은 **월중 ETF + 월말 ETF 모두**를 대상으로 한다.
월말 공시 직후에 작성 요청이 와도 월중 ETF를 빠뜨리면 안 된다.

> 2026년 6월 오류 사례: 월말 데이터만 사용해 RISE 미국AI밸류체인(2.25%)을 분배율 1위로 기재했으나,
> 실제 1위는 ACE미국반도체데일리타겟커버드콜(합성)(3.04%, 월중)이었다.

데이터 추출 후 반드시 아래를 출력해 확인:
```python
import json, sys
sys.stdout.reconfigure(encoding='utf-8')
with open('data/output/latest.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

ym = 'YYYY-MM'  # 분석 월로 변경
all_monthly = [d for d in data if d.get('current')
               and d.get('freq') in ('월배당','월배당추정')
               and d.get('ex_date','').startswith(ym)]

mid = [d for d in all_monthly if d.get('timing') == '월중']
eom = [d for d in all_monthly if d.get('timing') == '월말']
print(f'월중 {len(mid)}개 + 월말 {len(eom)}개 = 합계 {len(all_monthly)}개')

by_rate = sorted(all_monthly, key=lambda x: x.get('rate',0), reverse=True)
print('=== 통합 분배율 TOP 5 ===')
for i, d in enumerate(by_rate[:5], 1):
    print(f'{i}위 [{d["timing"]}] {d["name"]} {d["rate"]}%')
```

월중·월말 합산 숫자가 합리적인지 확인 후 진행.

### 1단계: 데이터 추출

```python
import json, sys
sys.stdout.reconfigure(encoding='utf-8')
with open('data/output/latest.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
# ⚠️ timing 필터 없음 — 월중+월말 전체 대상
# 분석 기준월: 요청한 달 (예: "6월" → ex_date startswith '2026-06')
target = [d for d in data if d.get('current')
          and d.get('freq') in ('월배당','월배당추정')
          and d.get('ex_date','').startswith('YYYY-MM')]
```

추출할 데이터:
- 월배당 ETF 중 current=True인 항목 (월중+월말 전체)
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
  <tr><th>주가 순위</th><th>ETF</th><th>주가 수익률</th><th>총수익률</th><th>분배 기여</th><th>총수익 순위</th></tr>
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
  <tr><th>주가 순위</th><th>ETF</th><th>주가 수익률</th><th>총수익률</th><th>분배 기여</th><th>총수익 순위</th></tr>
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

## 쇼츠 자료 작성 요청 시

"N월 [월중/월말] 쇼츠 만들어줘" 요청이 오면 아래 순서로 진행한다.

### 출력물 3종

| 파일 | 경로 |
|---|---|
| 슬라이드 HTML | `shorts/YYYY-MM-[mid/eom]-shorts.html` |
| AI 음성 스크립트 | `shorts/YYYY-MM-[mid/eom]-script.txt` |
| 슬라이드 이미지(6장) | `shorts/YYYY-MM-[mid/eom]-images/slide-01.png` ~ `slide-06.png` |

---

### 1단계: 데이터 추출

월중/월말 현황 작성 시와 동일한 Python 코드로 추출한다.
쇼츠에 사용할 핵심 데이터:
- 전체/상승/하락 개수
- 분배율 TOP 3 (ETF명, 분배율, 전월비%)
- 이달의 체크포인트 2개: ✅ 주목 케이스 1개 + ⚠️ 주의 케이스 1개
- 수익률 순위 변화 1개 케이스: 주가순위 → 총수익순위, 분배기여%
- 이달 전반적 흐름 한 문장

---

### 2단계: HTML 슬라이드 생성

`shorts/2026-05-eom-shorts.html`을 기반으로 데이터를 교체해 새 파일을 생성한다.

**슬라이드 6장 구조:**

| # | 섹션 | 핵심 내용 |
|---|---|---|
| 1 | 타이틀 | "YYYY년 N월 [월중/월말] 배당 ETF 분배금 점검" + ETF 수 |
| 2 | 이달 요약 | 전체/상승/하락 통계 카드 3개 + 흐름 한 문장 카드 |
| 3 | 분배율 TOP 3 | 순위 표(ETF명/분배율/전월비) + ⚠️ 주의 카드(감소 중인 경우) |
| 4 | 이달의 체크포인트 | ✅ 3개월 추이 카드 + ⚠️ 주의 케이스 카드 |
| 5 | 분배금의 힘 | 주가순위 → 총수익순위 변화 (숫자 크게) + 인사이트 카드 |
| 6 | 마무리 | 📈 이모지 + "매달 업데이트" + URL + 구독/좋아요 버튼 |

**디자인 토큰 (변경 금지):**
```css
--bg: #0d2818;          /* 다크 그린 배경 */
--accent: #6cba8b;      /* 태그/강조 */
--bright: #4ade80;      /* 상승/긍정 숫자 */
--warn: #fbbf24;        /* 주의 노랑 */
--red: #f87171;         /* 하락/구독 버튼 */
--sub: #9bbfac;         /* 보조 텍스트 */
컨테이너: height:100vh; width:calc(100vh*9/16)  /* 9:16 비율 고정 */
```

**동작:**
- 클릭 또는 스페이스바/→키로 슬라이드 전환
- 하단 도트로 현재 위치 표시
- 슬라이드 전환 시 좌→우 페이드 애니메이션 (0.35s)

**월중/월말 구분:**
- 슬라이드 1 태그: "월중 현황" 또는 "월말 현황"
- 나머지 구조와 디자인 동일

---

### 3단계: AI 음성 스크립트 작성

합쇼체(~입니다, ~습니다)로 작성. 총 35~40초 기준.

```
===================================================
N월 [월중/월말] 배당 ETF 분배금 점검 — 쇼츠 스크립트
===================================================

[슬라이드 1 — 타이틀] (약 4초)
안녕하세요, 배당픽입니다.
YYYY년 N월 [월중/월말] 배당 ETF 분배금 점검 결과를 알려드립니다.

[슬라이드 2 — 이달 요약] (약 7초)
이번 달 [월중/월말] 배당 ETF XX개가 확정됐습니다.
XX개 상승, XX개 하락으로 [흐름 한 문장].

[슬라이드 3 — 분배율 TOP 3] (약 8초)
분배율 상위 3개입니다.
1위는 [ETF명], XX%로 전월보다 XX% [올랐/내렸]습니다.
[주의 케이스가 있으면] XX위는 분배율은 높지만 분배금은 X개월째 줄고 있어 주의가 필요합니다.

[슬라이드 4 — 체크포인트] (약 8초)
이달의 체크포인트입니다.
[ETF명]은 [X월 XX원→X월 XX원→X월 XX원]으로 [N]개월 연속 [상승/하락]했습니다.
[주의 케이스 한 문장].

[슬라이드 5 — 분배금의 힘] (약 7초)
분배금이 수익률 순위를 바꾸기도 합니다.
주가 수익률 X위였던 [ETF명]은 분배금 X.XX% 덕분에 총수익률 기준 X위로 올라섰습니다.

[슬라이드 6 — 마무리] (약 5초)
월배당 ETF 분배금 현황은 배당픽에서 매달 확인하세요.
구독과 좋아요 부탁드립니다.

===================================================
TTS 주의: 긴 ETF명은 테스트 후 필요 시 줄여서 사용
===================================================
```

---

### 4단계: 슬라이드 이미지 저장

**사전 조건:** `localhost:8787`에 서버가 실행 중이어야 함 (`.claude/launch.json`의 `etf-site` 서버).
Playwright가 설치되어 있어야 함: `pip install playwright && python -m playwright install chromium`

**이미지 캡처 Python 코드:**
```python
import asyncio, os
from playwright.async_api import async_playwright

# 아래 두 줄만 요청에 맞게 수정
HTML_FILE = 'shorts/YYYY-MM-XXX-shorts.html'   # 예: shorts/2026-06-mid-shorts.html
OUT_DIR   = 'shorts/YYYY-MM-XXX-images'         # 예: shorts/2026-06-mid-images

async def capture():
    os.makedirs(OUT_DIR, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={'width': 540, 'height': 960})
        await page.goto(f'http://localhost:8787/{HTML_FILE}')
        await page.wait_for_load_state('networkidle')
        await page.wait_for_timeout(800)
        for i in range(1, 7):
            await page.screenshot(path=f'{OUT_DIR}/slide-{i:02d}.png')
            if i < 6:
                await page.click('#stage')
                await page.wait_for_timeout(500)
        await browser.close()
        print(f'완료: {OUT_DIR}/slide-01~06.png')

asyncio.run(capture())
```

서버 시작 → HTML 생성 확인 → Python 실행 순서로 진행한다.

---

### 5단계: 유튜브 쇼츠 제목 및 설명 작성

HTML·스크립트·이미지 생성 후 아래 형식으로 함께 출력한다.

**제목 — 3개 제안 (선택지 제공):**
```
① [핵심 수치] 포함형 — "N월 [월중/월말] 배당 ETF XX개 결산 — [핵심 한 줄]"
② [궁금증 유발]형 — "[이달 주목 현상]? N월 [월중/월말] 배당 점검"
③ [시황 키워드]형 — "[시장 이슈]에 [영향] — N월 [월중/월말] 결과"
```
- 100자 이내
- 숫자(ETF 수, 분배율%) 포함 시 클릭률 유리
- "역전", "바꿨다", "연속 상승" 등 동적 표현 활용

**동영상 설명 형식:**
```
YYYY년 N월 [월중/월말] 배당 ETF XX개 분배금 확정 결과를 정리했습니다.

📊 이달 요약
• 전체 XX개 | 상승 XX개 · 하락 XX개
• 분배율 1위: [ETF명] X.XX%
• [이달 주목 케이스 1줄]
• [수익률 순위 변화 1줄]

📌 월배당 ETF 분배금 현황은 배당픽에서 매달 확인하세요. 사이트 바로가기는 제 채널 프로필 링크(홈 화면)에 있습니다.

#월배당ETF #배당ETF #커버드콜ETF #분배금 #ETF투자 #배당투자 #월배당 #[이달주요ETF축약] #배당픽 #ETF분석
```

**해시태그 규칙:**
- 고정 태그: `#월배당ETF #배당ETF #커버드콜ETF #분배금 #ETF투자 #배당투자 #월배당 #배당픽 #ETF분석`
- 가변 태그 1개: 이달 분배율 1위 ETF 운용사·브랜드명 (예: `#TIGER배당커버드콜`, `#KODEX200`, `#PLUS테슬라`)

---

## 비정기 분배금 추가 요청 시

"[ETF명] 비정기 분배금 추가해줘" + 배당락일·분배금이 오면 아래 순서로 진행한다.

### ⚠️ 핵심 주의사항

비정기 분배 ETF(월배당이 아닌 ETF)의 배당락일이 20일 이하(예: 6월 19일)이면,
`build_latest`의 target_dates 계산에서 실제 월중 기준일(예: 6월 15일)을 밀어낼 수 있다.
→ **2026-06 이후 버전에서는 월배당/월배당추정 ETF 날짜만 target_dates에 반영하도록 수정되어 있으므로 자동 처리됨.**
→ 만약 current=True 항목이 비정상적으로 줄어들면 이 버그를 의심할 것.

### 1단계: XLS 파일 배치 후 프로세서 실행

`data/raw/YYYY년 MM월/` 폴더에 XLS 파일을 넣은 뒤:

```bash
python -X utf8 etf_data_processor.py
```

### 2단계: 결과 확인

```
✅ 전체 NNN개 (현재 기간 월중 NN개 / 월말 NNN개)
```

- 월중/월말 수치가 직전과 비슷한지 확인 (비정기 ETF 추가로 갑자기 줄어들면 버그)
- 비정기 ETF 자체는 current=False로 처리되는 게 정상

### 3단계: git push

```bash
git add data/output/latest.json data/output/history.json data/output/etf_data.js index.html
git commit -m "data: [ETF명] 비정기 분배금 추가 (YYYY-MM-DD, NNN원)"
git push
```

### 4단계: 상장일·수익률 업데이트 (신규 ETF인 경우)

비정기 ETF가 이 사이트에 **처음 등록되는 경우**, 상장일(`listed_date`)과 수익률(`return_1m` 등)이 없다.
- `--prices-only`가 실행될 때 `etf_meta.json`에 없는 신규 코드를 자동 감지해 메타를 즉시 조회함
- GitHub Actions가 매일 `--prices-only`를 실행하므로 **다음날 자동으로 채워짐**
- 당일 즉시 반영이 필요하면 아래 방법 사용

**즉시 반영하려면:**

방법 ①: GitHub Actions 수동 트리거 (권장)
```bash
gh workflow run "Daily Price Update"
```

방법 ②: 로컬 직접 실행
```bash
python -X utf8 etf_data_processor.py --prices-only
git add data/output/latest.json data/output/etf_data.js data/output/etf_meta.json index.html
git commit -m "chore: 신규 ETF 상장일·수익률 업데이트"
git push
```

---

## 비정기 분석 작성 시

"[주제] 분석해줘" 또는 "[주제] 글 작성해줘" 요청이 오면:
- 동일한 HTML 출력 방식 사용
- 섹션 구조는 내용에 맞게 자유롭게
- 주의사항 문구는 동일하게 포함

---

## ⚠️ 프로세서 재실행 시 콘텐츠 분배율 확인

프로세서(`etf_data_processor.py`)를 재실행하면 현재 종가가 새로 반영되어 분배율(`rate`)이 바뀐다.
공시일 전일 종가 조회에 실패한 ETF(약 322개)는 **현재 종가 fallback**으로 처리되기 때문이다.

→ 프로세서를 재실행한 경우, 이미 작성된 콘텐츠(인사이트 글, 네이버 블로그 글)의 분배율 순위가 바뀌지 않았는지 반드시 확인하고, 달라졌으면 수정 후 push한다.

---

## 네이버 블로그 표 작성 방식

네이버 블로그에 붙여넣을 표는 코드 블록(```) 없이, 마크다운 표 형식 그대로 본문에 작성한다.

| 순위 | ETF | 분배금 | 전월비 | 분배율 |
|---|---|---|---|---|
| 1위 | ETF명 | 000원 | +0.0% | 0.00% |

- `|---|` 구분선 포함
- 코드 블록으로 감싸지 않음
- 글 전체도 코드 블록 없이 일반 텍스트로 출력

---

## 네이버 블로그 글 작성 시

"N월 [일정 안내 / 확정 공지 / 현황 점검 / 분석 글] 네이버 블로그 글 작성해줘" 요청이 오면 아래 양식을 사용한다.

**공통 원칙:**
- 작성 주체는 배당픽이 아닌 블로그 운영자 본인 (1인칭 "안녕하세요" 없음)
- 배당픽 사이트 URL은 별도 줄로 분리하지 않고 본문 문장 안에 `배당픽(baedangetf.com)` 형식으로 삽입
- 배당픽 인사이트 글로 유도할 때는 해당 글이 이미 게시된 경우에만 언급
- 투자 고지 문구: `※ 본 내용은 투자 권유가 아니며, 최종 투자 판단은 본인에게 있습니다.`

---

### 양식 ①: 일정 안내 (월중/월말 공통)

카테고리: 분배금 현황

```
[제목] YYYY년 N월 [월중/월말] 배당 ETF 일정 안내 — 최종 매수일은 MM월 DD일

월배당 ETF 중 매월 [15일/말일] 전후에 배당락이 발생하는 상품을 [월중/월말] 배당 ETF라고 합니다.
TIGER, KODEX, ACE, RISE, PLUS 등 국내 주요 운용사에서 [월중/월말] 배당 상품을 운용하고 있습니다.

N월 [월중/월말] 배당 ETF 일정이 확정됐습니다.

[표]
구분 | 날짜
최종 매수일 | YYYY년 MM월 DD일 (요일)
배당락일 | YYYY년 MM월 DD일 (요일)
기준일 | YYYY년 MM월 DD일 (요일)

이번 달 분배금을 받으려면 MM월 DD일(요일)까지 매수가 완료돼야 합니다.
ETF도 주식과 마찬가지로 매수 당일 체결되므로 DD일 장중에 매수하면 됩니다.
DD+1일 배당락일 이후 매수하면 이번 달 분배금 지급 대상에서 제외됩니다.

어떤 ETF가 [월중/월말] 배당 대상인지, 각 상품의 분배율과 분배금 추이는
배당픽(baedangetf.com)에서 확인할 수 있습니다.
달력 기능을 통해 배당락일과 최종 매수일도 한눈에 볼 수 있으니 참고하시기 바랍니다.

※ 본 내용은 투자 권유가 아니며, 최종 투자 판단은 본인에게 있습니다.

#월배당ETF #배당ETF #배당락일 #최종매수일 #N월배당 #[월중/월말]배당 #배당픽
```

---

### 양식 ②: 분배금 확정 공지 (월중/월말 공통)

카테고리: 분배금 현황
업로드 시점: 분배금 공시 직후 (현황 점검 글 게시 전)

```
[제목] YYYY년 N월 [월중/월말] 배당 ETF 분배금 확정 — 분배율 1위 [ETF명] X.XX%

N월 [월중/월말] 배당 ETF 분배금이 공시됐습니다.
전체 XX개 상품 중 전월 대비 상승 XX개, 하락 XX개, 동일 XX개였습니다.

이번 달 분배율 상위 5개 상품은 아래와 같습니다.

[표]
순위 | ETF | 분배금 | 전월비 | 분배율
1위 | [ETF명] | XXX원 | +X.X% | X.XX%
2위 | ...
3위 | ...
4위 | ...
5위 | ...

분배율 상위권에 있더라도 전월 대비 감소 중인 상품이 있으니
분배율 수치와 함께 추이를 확인하는 것이 좋습니다.

전체 XX개 상품의 분배금과 분배율 순위는 배당픽(baedangetf.com)에서 바로 확인할 수 있습니다.
분배율 랭킹, 배당 일정 달력, 수익률 비교 기능도 함께 제공하니 월배당 ETF 투자에 활용해 보시기 바랍니다.
이번 달 전체 분배금 흐름에 대한 분석 글도 곧 업로드할 예정입니다.

※ 본 내용은 투자 권유가 아니며, 최종 투자 판단은 본인에게 있습니다.

#월배당ETF #배당ETF #분배금 #커버드콜ETF #ETF투자 #월배당 #배당픽 #[월중/월말]배당 #[분배율1위ETF브랜드]
```

---

### 양식 ③: 현황 점검 (월중/월말 공통)

카테고리: 분배금 현황
업로드 시점: 배당픽 인사이트 현황 글 게시 후

```
[제목] YYYY년 N월 [월중/월말] 배당 ETF 분배금 점검 — [이달 핵심 한 줄]

월배당 ETF는 매월 분배금을 지급하는 상장지수펀드입니다.
이 중 [월중/월말] 배당 ETF는 매월 [15일/말일] 전후에 배당락이 발생하는 상품입니다.

이번 달 [월중/월말] 배당 ETF XX개의 분배금이 확정됐습니다.
전월 대비 상승한 상품이 XX개, 하락이 XX개, 동일이 XX개였습니다.
[이달 전반적 흐름 한 문장]

**이번 달 분배율 상위 5개 상품**

[표]
순위 | ETF | 분배금 | 전월비 | 분배율
1위 | ...
2위 | ...
3위 | ...
4위 | ...
5위 | ...

[핵심 포인트 2~3개 — 구체적 ETF명 포함, 각 2~4문장]

▶ [포인트 제목]
[내용]

▶ [포인트 제목]
[내용]

분배율 TOP 10, 분배금 TOP 10, 수익률 순위 변화까지 전체 분석 내용은
배당픽(baedangetf.com) 인사이트 게시판에서 확인할 수 있습니다.
분배율 랭킹, 배당 일정 달력, 수익률 비교 기능도 함께 제공하니 월배당 ETF 투자에 활용해 보시기 바랍니다.

※ 본 내용은 투자 권유가 아니며, 최종 투자 판단은 본인에게 있습니다.

#월배당ETF #배당ETF #커버드콜ETF #분배금 #ETF투자 #월배당 #배당픽 #[월중/월말]배당
```

---

### 양식 ④: 월간 분석

카테고리: 월간 분석
업로드 시점: 배당픽 인사이트 분석 글 게시 후

```
[제목] YYYY년 N월 월배당 ETF 분석 — [이달 핵심 한 줄]

N월 월배당 ETF 전체 흐름을 분석한 글이 배당픽에 올라왔습니다. 핵심 내용만 먼저 소개합니다.

[이달 전체 흐름 요약 2~3문장]

**[소제목 — 구체적 ETF명 포함]**
[내용 3~5문장. 상승/하락 수치, 전월 대비 변화, 시장 맥락 포함]

**[소제목 — 구체적 ETF명 포함]**
[내용 3~5문장]

**[소제목 — 필요 시 추가]**
[내용]

[분석 주제 — 예: 같은 기초지수, 다른 전략 비교 등]
[내용 3~5문장. 주요 ETF명 명시]

분배율 뒤집어보기, 추세 점검, [이달 비교 주제] 전체 분석은
배당픽(baedangetf.com) 인사이트 게시판에서 확인할 수 있습니다.
분배율 랭킹, 달력, 수익률 비교 등 다양한 기능도 함께 제공하니 월배당 ETF 투자에 활용해 보시기 바랍니다.

※ 본 내용은 투자 권유가 아니며, 최종 투자 판단은 본인에게 있습니다.

#월배당ETF #배당ETF #커버드콜ETF #분배금분석 #ETF투자 #배당투자 #배당픽 #N월배당 #[이달주요ETF브랜드]
```

---

## 네이버 증권 홍보글 작성 시

"[ETF명] 네이버 증권 홍보글 작성해줘" 요청이 오면 아래 양식을 사용한다.

**목적:** 배당픽(baedangetf.com) 유입 유도
**게재 위치:** 네이버 증권 해당 ETF 종목 토론/게시판

**공통 원칙:**
- 분배금 확정 직후 작성 (데이터 공시 후)
- 순위는 반드시 데이터로 검증 후 기재 (추정 금지)
- 투자 권유 표현 금지 ("추천", "사세요" 등)
- 배당픽 URL은 마지막에 단독 줄로 표기: `baedangetf.com`

**주목할 만한 각도 (우선순위 순):**
1. 3개월 연속 상승/하락 추이
2. 같은 기초자산 내 전략 비교 (OTM vs ATM, 고정 vs 타겟 등)
3. 월말/월중 배당 ETF 중 분배율 순위
4. 전월 대비 큰 폭 변화 (+20% 이상 또는 -20% 이하)

```
[제목] N월 분배금 XXX원, [주목 포인트 한 줄]

N월 분배금 XXX원 확정됐습니다. [N-2]월 XXX원 → [N-1]월 XXX원 → N월 XXX원으로 [추이 설명], 전월 대비 +X.X% [올랐/내렸]습니다. 이번달 [월중/월말] 배당 ETF XXX개 중 분배율 X.XX%로 X위입니다.

[전략 특성 또는 비교 포인트 2~4문장. 같은 기초자산 대비 차별점, 시장 환경과의 연관성 등]

월배당 ETF 전체 분배율·분배금 순위는 여기서 확인할 수 있습니다.
baedangetf.com
```

**작성 예시 (KODEX 미국나스닥100데일리커버드콜OTM, 2026년 6월):**

```
제목: 6월 분배금 185원, 3개월 연속 상승 중인 나스닥100 OTM 커버드콜 ETF

6월 분배금 185원 확정됐습니다. 4월 169원 → 5월 182원 → 6월 185원으로 3개월 연속 상승 중이고, 전월 대비 +1.6% 올랐습니다. 이번달 월말 배당 ETF 126개 중 분배율 1.68%로 8위입니다.

같은 나스닥100 기반인 ATM 커버드콜 ETF보다 분배율은 낮지만, OTM(외가격) 콜옵션 구조라 지수가 오를 때 상승분을 일부 가져갈 수 있습니다. 나스닥 반등이 이어지는 국면에서 성장성과 월배당을 함께 가져가고 싶은 분들에게 맞는 선택지일 수 있습니다.

월배당 ETF 전체 분배율·분배금 순위는 여기서 확인할 수 있습니다.
baedangetf.com
```

---

## 운용사 정보 관리

운용사명은 `etf_data_processor.py`의 `BRAND_TO_COMPANY` 딕셔너리로 관리한다.

**처리 우선순위:**
1. `BRAND_TO_COMPANY` 매핑 (브랜드명 기준, 가장 정확)
2. 네이버 파싱 결과 (`etf_meta.json` 캐시)
3. 브랜드명 그대로 사용 (fallback)

**주의사항:**
- 네이버 파싱은 상장일 조회 겸용이나 운용사 파싱이 틀릴 수 있음 (관련 뉴스 등 엉뚱한 내용 파싱)
- 신규 브랜드가 데이터에 등장하면 반드시 `BRAND_TO_COMPANY`에 직접 추가
- 브랜드 추출 시 ETF명 앞부분을 잘라서 쓰므로 일부 브랜드가 잘릴 수 있음 (예: DAISHIN → DAISHI)
- 신규 브랜드 확인 방법:
  ```python
  python -X utf8 -c "
  import json
  with open('data/output/latest.json', encoding='utf-8') as f: data = json.load(f)
  brands = sorted(set(d.get('brand','') for d in data if d.get('brand')))
  print(brands)
  "
  ```

---

## ⚠️ 예정 작업: 분배금 평가지표

현재 지표(변동성·추세·수준)는 **분배금 자체만** 보고 투자자가 실제로 벌었는지는 평가하지 않는다.
개선 방향을 검토했고 **분배금 backfill 완료 후** 진행하기로 했다(2026-07-26).

- 검토 기록·폐기한 접근·설계 원칙: **[docs/distribution_metrics.md](docs/distribution_metrics.md)**
- 결정된 방향: 전 기간 backfill → 수익률 차트(주가·총수익 병기) → 전 기간 분배금 기여도 평가
- ⚠️ **이미 폐기한 접근을 다시 제안하지 말 것** — 단일 기간 판정(시점에 따라 뒤집힘),
  커버드콜 그룹 내 백분위(기초자산이 55종으로 제각각). 상세 근거는 위 문서에 있음

---

## ⚠️ 예정 작업: price_history 저장소 분리

`data/output/price_history/`(915개, 29MB)가 매일 갱신·커밋되며 저장소가 **하루 약 1MB, 연 245MB**씩 커진다.
**문제가 되기 전에 미리 분리하기로 결정**(2026-07-26). 아직 실행 전.

- 계획·실측·비용 조사: **[docs/price_history_scaling.md](docs/price_history_scaling.md)**
- 방식 후보: 별도 GitHub 저장소(⑤) 또는 Cloudflare R2(①) — 둘 다 비용 $0
- 사용자가 "종가 파일 분리하자"고 하면 위 문서를 먼저 읽을 것

> 참고: `data/raw`(원본 XLS)는 git에서 0.3MB(전체의 0.9%)라 **용량 걱정 대상이 아니다.**

---

## KIND 자동 수집 스크립트

- `kind_client.py` — KIND 접근 공용 모듈. 검색은 Playwright(브라우저), 문서 다운로드는 순수 HTTP.
  - 검색 엔드포인트는 curl/urllib 요청을 차단하므로 브라우저가 필요하다
  - 검색 시 `reportNm`이 아니라 **`reportNmTemp`** 에 검색어를 넣어야 한다 (fnSearch가 덮어씀)
  - 정정 공시는 뷰어 `mainDoc`의 최신(Y) 버전을 자동 선택
- `kind_fetch.py` — 분배금 공시(XLS) 수집 → `data/raw/YY년 M월/`
- `kind_schedule.py` — 설정/환매 공시에서 최종매수일·배당락일·기준일 산출
- `kind_meta.py` — data/raw에 있는데 메타 캐시에 없는 신규 종목의 메타 보충 (프로세서 전에 실행)
- `kind_verify.py` — 프로세서 결과가 사이트에 올려도 되는 상태인지 검증 (통과 0 / 실패 1)

### ⚠️ KIND 수집의 함정 3가지 — 모두 "조용히" 실패한다

실측으로 확인한 제약. 오류가 나지 않고 결과만 잘려서 나오므로 특히 위험하다.

| 제약 | 증상 | 대응 |
|---|---|---|
| **한 페이지 100건 상한** | 초과분이 잘림. 최신순이라 **오래된 것부터 사라진다** | `kind_client._search_once()`가 **페이지를 넘겨가며** 수집 |
| **검색 기간 3년 초과 시 0건** | 5년 범위로 검색하면 **오류 없이 0건** 반환 | `kind_fetch.py`가 월 단위로 쪼개 검색 |
| **같은 회사·같은 날 여러 건 → 파일명 충돌** | KIND 파일명에 접수번호가 없어 **서로 다른 공시가 같은 이름**이 된다. "이미 있음"으로 건너뛰어 **뒤 건이 통째로 사라진다** | `kind_fetch.py`가 기존 파일과 **내용을 비교**하고, 다르면 `… [접수번호].xls`로 따로 저장 |

> ⚠️ **날짜 분할만으로는 부족하다.** ETF 결산 분배가 몰리는 4월 말에는 **하루에도 100건이 넘는다**
> (2018-04-26 160건, 2019-04-26 197건). 하루로 좁혀도 상한에 걸리므로 페이지네이션이 필수다.
> 2026-07-27 backfill에서 이 문제로 176건이 누락됐다가 페이지네이션 구현 후 복구했다.
> (2017-04 19건 + 2018-04 60건 + 2019-04 97건)

> 실측: 2018년을 한 번에 검색하면 100건, 상·하반기로 나누면 100+77=177건.
> `이익금분배`를 2005~2009(5년)로 검색하면 0건이지만 2009년 단독으로는 77건.

> ⚠️ **파일명 충돌은 정정공시와 구분해야 한다.** 접수번호가 다르다고 항상 다른 공시는 아니다.
> KIND 뷰어는 정정된 공시를 조회하면 원본 접수번호로 요청해도 **최신 정정본을 돌려준다.**
> 그래서 원본+정정 쌍은 내용이 같고(건너뛰는 게 맞다), 진짜 별건은 내용이 다르다.
> **파일명이 아니라 내용으로 판단할 것.**
>
> 2026-08-01 감사: 2019-07~2026-05에서 **65건이 이 버그로 통째로 누락**돼 있었다(분배 기록 605건,
> 342종목). 제보 계기는 PLUS 고배당주(161510)의 2022-04 분배금 누락 — 그날 한국예탁결제원이
> 일괄공시를 2건 냈는데 161510이 든 뒤 건이 버려졌다. 같은 회사가 하루에 최대 5건까지 낸 적 있다
> (2021-04-28 한국펀드파트너스).

**직접 `kind_client.search_disclosures()`를 호출할 때는 기간을 1년 이내로 끊을 것.**

### 분배금 backfill — 완료됨 (2026-07-27). 실질 한계는 2019-07

**backfill은 이미 전 구간 완료했다. 다시 돌릴 필요 없다.**

> ⚠️ **2019년 중반 이전 공시는 받아뒀지만 파싱할 수 없다.** 그 시절엔 공시 형식이 달랐다.
>
> | 기간 | 형식 | 종목코드 | 파싱 |
> |---|---|---|---|
> | 2009-09 ~ 2019 상반기 | **개별공시** (ETF 1건당 공시 1건, 1,551건) | ❌ 없음 | **불가** |
> | 2019 하반기 ~ 현재 | **일괄공시** (표 형식, 413건) | ✅ ISIN | 가능 |
>
> 개별공시에는 펀드 정식명(`대신 GIANT 현대차그룹 증권 상장지수형 투자신탁[주식]`)만 있고
> 종목코드가 없어 현재 ETF와 연결할 수 없다. 이름 매칭은 개명·상장폐지 때문에 신뢰하기 어렵다.
> **원본 파일은 보존한다** — 용량 부담이 작고(git 압축 후 수 MB), 나중에 매칭 방법을 찾으면
> 재활용할 수 있으며, KIND에서 과거 공시가 내려갈 가능성도 있기 때문.

- 공시 존재 범위: 2009-09-07 최초 ~ 현재. 187개월, 총 1,828건 (2026-07-27 전수 감사)
  - 2009 상반기에 `이익금분배`로 검색되는 건들은 ETF가 아니라 부동산·특별자산 펀드 것이다
- **실제 데이터 보유: 2019-07-31부터** (일괄공시 전환 시점). 분배 이력 8,340건 / 종목 1,014개
  - 2026-08-01에 파일명 충돌 버그로 누락됐던 605건을 복구해 반영한 수치 (그 전 7,735건 / 1,008개)
- 이 덕분에 현재 노출 종목의 **87%(158/182)**가 상장이후 전 구간 커버 (backfill 전 36%)
  - 이 비율은 상장일에만 좌우되므로 복구 전후로 바뀌지 않는다. 달라진 건 각 종목의 **이력 밀도**다

**추가 수집이 필요할 때만** (평소에는 `kind-watch.yml`이 자동 처리):

```bash
python -X utf8 kind_fetch.py --from 2024-01 --to 2024-12   # 연 단위 권장
```

---

## 사이트 주요 데이터 파일

- `data/output/latest.json` — 현재 ETF 분배금 데이터 (분배율, 분배금, 추이 등)
- `data/output/etf_data.js` — ETF 전체 데이터 (수익률 포함)
- `data/output/history.json` — 분배금 히스토리 데이터 (월별 누적)
- `data/output/price_history/{code}.json` — 종목별 상장일~오늘 전체 일별 종가 이력 (915개 파일, ~29MB. `--prices-only` 실행 시 자동 갱신)
- `insight/posts.json` — 인사이트 글 목록
- `insight/posts/` — 개별 글 파일

## 사이트 주요 페이지

- `index.html` — 메인
- `insight.html` — 인사이트 목록
- `admin.html` — 관리자 작성 페이지 (비밀번호 보호)
- `api/publish.js` — 게시 서버리스 함수
- `ranking.html` — 랭킹
  - **'월배당 ETF 분배율 분배금' 탭**: 월말 기준으로만 업데이트됨. 월중 데이터 업데이트 시 랭킹 카드에는 반영되지 않고 상세 페이지에만 반영됨. 월말 데이터 업데이트 시 함께 반영됨. (안내 박스가 자동 표시됨)
  - **'전체 ETF 기간별 수익률' 탭**: 매일 자동 갱신 (GitHub Actions)
- `portfolio.html` — MY ETF
