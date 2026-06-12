"""
배당픽 스레드 포스트 생성기
============================
데이터 업데이트 후 자동 실행되어 posts/ 폴더에 PNG + TXT 저장

사용법:
  python generate_post.py              # 날짜로 월중/월말 자동 판단
  python generate_post.py --timing 월말 # 강제 지정
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Windows 콘솔 UTF-8 출력
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        pass

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Pillow 미설치: pip install Pillow")
    sys.exit(1)

# ── 설정 ────────────────────────────────────────────────
LATEST_JSON = 'data/output/latest.json'
OUTPUT_DIR  = 'posts'
TOP_N       = 5
IMG_SIZE    = (1080, 1080)

# 사이트 컬러 (index.html :root 와 동일)
C_BG      = (26,  26,  24)    # --ink   #1a1a18
C_WHITE   = (255, 255, 255)
C_GREEN   = (108, 186, 139)   # --accent-mid #6cba8b
C_GREEN2  = (29,  107, 56)    # --accent #1d6b38
C_GRAY    = (154, 154, 147)   # --ink3  #9a9a93
C_GRAY2   = (74,  74,  69)    # --ink2  #4a4a45
C_BORDER  = (108, 186, 139, 45)

# ── 폰트 ────────────────────────────────────────────────
FONT_CANDIDATES = {
    'regular': [
        'C:/Windows/Fonts/malgun.ttf',                                      # Windows 맑은고딕
        '/usr/share/fonts/truetype/nanum/NanumGothic.ttf',                  # Ubuntu (CI)
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/System/Library/Fonts/AppleSDGothicNeo.ttc',                       # macOS
    ],
    'bold': [
        'C:/Windows/Fonts/malgunbd.ttf',
        '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
        'C:/Windows/Fonts/malgun.ttf',
        '/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
    ],
}

def _load_font(kind, size):
    for path in FONT_CANDIDATES[kind]:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    print(f"[경고] 한글 폰트를 찾지 못했습니다. 기본 폰트 사용")
    return ImageFont.load_default()

def fonts(size):
    return _load_font('regular', size)

def fontsb(size):
    return _load_font('bold', size)

# ── 이미지 생성 ──────────────────────────────────────────
def generate_image(timing_label, month_label, etfs, pay_date):
    W, H = IMG_SIZE
    img  = Image.new('RGB', (W, H), C_BG)
    draw = ImageDraw.Draw(img, 'RGBA')
    PAD  = 72

    # ── 상단: 로고 + 날짜 ──
    y = PAD
    box = [PAD, y, PAD + 54, y + 54]
    draw.rounded_rectangle(box, radius=10, fill=C_GREEN2)
    draw.text((PAD + 13, y + 11), '₩', font=fontsb(30), fill=C_WHITE)
    draw.text((PAD + 68, y + 11), '배당픽', font=fontsb(34), fill=C_WHITE)

    date_str = datetime.now().strftime('%Y.%m.%d')
    draw.text((W - PAD, y + 13), date_str, font=fonts(28), fill=C_GRAY, anchor='ra')

    # ── 타이틀 ──
    y += 84
    draw.text((PAD, y), month_label, font=fontsb(56), fill=C_GREEN)
    y += 68
    draw.text((PAD, y), f'{timing_label} 분배금 공시', font=fontsb(56), fill=C_WHITE)
    y += 80

    # ── 지급일 배지 ──
    if pay_date:
        badge_w = 380
        draw.rounded_rectangle([PAD, y, PAD + badge_w, y + 50], radius=8, fill=C_GREEN2)
        draw.text((PAD + 18, y + 11), f'지급일  {pay_date}', font=fontsb(26), fill=C_WHITE)
        y += 72

    # ── 구분선 ──
    draw.rectangle([PAD, y, W - PAD, y + 1], fill=(*C_GREEN, 60))
    y += 20
    draw.text((PAD, y), f'분배율 상위 {min(TOP_N, len(etfs))}개 ETF  (월배당 기준)',
              font=fonts(26), fill=C_GRAY)
    y += 44

    # ── ETF 목록 ──
    ROW_H = 96
    for i, e in enumerate(etfs[:TOP_N]):
        # 홀짝 줄 배경
        if i % 2 == 0:
            draw.rounded_rectangle(
                [PAD - 14, y - 6, W - PAD + 14, y + ROW_H - 10],
                radius=8, fill=(255, 255, 255, 10)
            )

        # 순위 숫자
        rank_col = C_GREEN if i == 0 else C_GRAY
        draw.text((PAD, y + 6), str(i + 1), font=fontsb(44), fill=rank_col)

        # ETF명 (최대 16자)
        name = e['name']
        if len(name) > 16:
            name = name[:15] + '…'
        draw.text((PAD + 54, y + 2), name, font=fontsb(36), fill=C_WHITE)

        # 브랜드
        draw.text((PAD + 54, y + 50), e.get('brand', ''), font=fonts(24), fill=C_GRAY)

        # 분배율 (우측 상단)
        rate_col = C_GREEN if i == 0 else C_WHITE
        draw.text((W - PAD, y + 2), f"{e['rate']}%",
                  font=fontsb(44), fill=rate_col, anchor='ra')

        # 분배금 (우측 하단)
        draw.text((W - PAD, y + 52), f"{int(e['dist']):,}원",
                  font=fonts(24), fill=C_GRAY, anchor='ra')

        y += ROW_H

    # ── 하단 구분선 + URL ──
    y += 6
    draw.rectangle([PAD, y, W - PAD, y + 1], fill=(*C_GREEN, 60))
    y += 24

    draw.text((PAD, y), 'baedangetf.com', font=fontsb(30), fill=C_GREEN)
    draw.text((W - PAD, y + 2), '전체 ETF 분배금 확인 →',
              font=fonts(26), fill=C_GRAY, anchor='ra')

    return img


# ── 텍스트 멘트 생성 ─────────────────────────────────────
def generate_text(timing_label, month_label, etfs, pay_date):
    medals = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣']
    lines = [
        f"📢 {month_label} {timing_label} ETF 분배금 공시",
        "",
    ]
    if pay_date:
        lines.append(f"💸 지급일: {pay_date}")
        lines.append("")

    lines.append(f"분배율 상위 {min(TOP_N, len(etfs))}개 (월배당 기준)")
    lines.append("")

    for i, e in enumerate(etfs[:TOP_N]):
        medal = medals[i] if i < len(medals) else f"{i+1}."
        lines.append(f"{medal} {e['name']}")
        lines.append(f"   {e['rate']}%  |  {int(e['dist']):,}원/좌")

    lines += [
        "",
        "👉 baedangetf.com",
        "",
        "#월배당ETF #ETF분배금 #배당투자 #배당픽 #월배당",
    ]
    return '\n'.join(lines)


# ── 메인 ────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--timing', choices=['월중', '월말'], default=None,
                        help='월중 또는 월말 (미지정 시 날짜 기준 자동 판단)')
    args = parser.parse_args()

    # timing 판단
    now = datetime.now()
    if args.timing:
        timing_label = args.timing
    else:
        timing_label = '월중' if now.day <= 20 else '월말'

    month_label = f"{now.year}년 {now.month}월"

    # latest.json 읽기
    try:
        with open(LATEST_JSON, 'r', encoding='utf-8') as f:
            latest = json.load(f)
    except FileNotFoundError:
        print(f"[오류] {LATEST_JSON} 없음")
        sys.exit(1)

    # 월배당 + current + timing 필터
    current = [
        e for e in latest
        if e.get('current')
        and e.get('freq') in ('월배당', '월배당추정')
        and e.get('timing') == timing_label
    ]
    current.sort(key=lambda x: float(x.get('rate', 0)), reverse=True)

    if not current:
        print(f"[스킵] 현재 공시 데이터 없음 (timing={timing_label})")
        sys.exit(0)

    # 지급일: 가장 많이 등장하는 값 사용
    pay_dates = [e.get('pay_date', '') for e in current if e.get('pay_date')]
    pay_date  = max(set(pay_dates), key=pay_dates.count) if pay_dates else ''

    # 출력 디렉토리
    Path(OUTPUT_DIR).mkdir(exist_ok=True)
    fname = f"{now.year}-{now.month:02d}-{timing_label}"

    # PNG 생성
    img      = generate_image(timing_label, month_label, current, pay_date)
    img_path = f"{OUTPUT_DIR}/{fname}.png"
    img.save(img_path, 'PNG')
    print(f"✅ 이미지: {img_path}")

    # TXT 생성
    text     = generate_text(timing_label, month_label, current, pay_date)
    txt_path = f"{OUTPUT_DIR}/{fname}.txt"
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f"✅ 텍스트: {txt_path}")

    # 터미널에 멘트 출력
    print("\n" + "═" * 52)
    print("📝 스레드 멘트")
    print("═" * 52)
    print(text)
    print("═" * 52)


if __name__ == '__main__':
    main()
