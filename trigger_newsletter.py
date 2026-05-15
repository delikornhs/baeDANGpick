"""
배당픽 뉴스레터 발송 트리거 스크립트
GitHub Actions에서 데이터 업데이트 후 자동 실행
"""
import json
import os
import sys
import requests
from datetime import datetime

APPS_SCRIPT_URL   = os.environ.get('APPS_SCRIPT_URL', '')
NEWSLETTER_SECRET = os.environ.get('NEWSLETTER_SECRET', '')
LATEST_JSON       = 'data/output/latest.json'
TOP_N             = 15   # 이메일에 포함할 ETF 수


def main():
    if not APPS_SCRIPT_URL:
        print("APPS_SCRIPT_URL 없음, 스킵")
        return
    if not NEWSLETTER_SECRET:
        print("NEWSLETTER_SECRET 없음, 스킵")
        return

    # latest.json 읽기
    try:
        with open(LATEST_JSON, 'r', encoding='utf-8') as f:
            latest = json.load(f)
    except FileNotFoundError:
        print(f"{LATEST_JSON} 없음, 스킵")
        return

    # 현재 기간 월배당 ETF 추출 (분배율 내림차순)
    current = [
        e for e in latest
        if e.get('current') and e.get('freq') in ('월배당', '월배당추정')
    ]
    current.sort(key=lambda x: float(x.get('rate', 0)), reverse=True)

    etfs = [
        {
            'name':  e['name'],
            'brand': e['brand'],
            'ex':    e['ex'],
            'pay':   e['pay'],
            'dist':  e['dist'],
            'rate':  e['rate'],
        }
        for e in current[:TOP_N]
    ]

    now   = datetime.now()
    month = f"{now.year}년 {now.month}월"

    payload = {
        'action': 'send_newsletter',
        'secret': NEWSLETTER_SECRET,
        'month':  month,
        'etfs':   etfs,
    }

    print(f"뉴스레터 발송 트리거: {month}, ETF {len(etfs)}개")
    try:
        r = requests.post(APPS_SCRIPT_URL, json=payload, timeout=60)
        print(f"응답: {r.text}")
    except Exception as e:
        print(f"발송 요청 실패: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
