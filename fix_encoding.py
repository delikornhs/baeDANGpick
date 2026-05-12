"""
HTML 파일의 이중 인코딩된 한글을 복구하는 스크립트.
원인: latin-1로 읽어 UTF-8로 저장하면서 한글이 이중 인코딩됨.
해결: 손상된 섹션만 encode('latin-1').decode('utf-8')으로 역변환.
"""
import pathlib

BASE = pathlib.Path(__file__).parent
p = BASE / "etf-dividend-v6.html"
html = p.read_text(encoding="utf-8")

# ── 섹션 경계 ──────────────────────────────────────────
# A: <head> ~ </head>  (fix_meta.py가 올바르게 쓴 메타태그 포함 → 건드리지 않음)
# B: <body> ~ const PRICE_DATE 직전  (손상된 HTML 본문 → 복구)
# D: const PRICE_DATE ~ const TODAY  (신선한 ETF 데이터 → 건드리지 않음)
# E: const TODAY ~ 파일 끝           (손상된 JS 함수 + footer → 복구)

body_start = html.find("<body>")
pd_start   = html.find("const PRICE_DATE")
if pd_start == -1:
    pd_start = html.find("const ETF_END")
today_start = html.find("const TODAY")

A = html[:body_start]
B = html[body_start:pd_start]
D = html[pd_start:today_start]
E = html[today_start:]

def fix(s):
    """이중 인코딩 역변환: UTF-8(latin-1 문자) → 원래 한글"""
    return s.encode("latin-1", errors="replace").decode("utf-8", errors="replace")

B_fixed = fix(B)
E_fixed = fix(E)

# 로고 텍스트를 새 브랜드명으로 교체 (분배금 달력 → 배당픽)
B_fixed = B_fixed.replace(
    '<div class="logo-mark">₩</div>분배금 달력',
    '<div class="logo-mark">₩</div>배당픽'
)

new_html = A + B_fixed + D + E_fixed
p.write_text(new_html, encoding="utf-8")

# 검증
checks = ["배당픽", "언제까지", "배당락일", "전날 종가", "이날부터 매도가능", "분배금 계산기"]
print("== 복구 검증 ==")
for w in checks:
    print(f"  {'✅' if w in new_html else '❌'} {w}")
print("완료")
