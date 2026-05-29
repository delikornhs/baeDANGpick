"""
배당픽 뉴스레터 발송 트리거 스크립트

사용법:
  # 일정 업데이트 뉴스레터 (기준일·배당락일·최종매수일)
  python trigger_newsletter.py --type schedule --timing 월중 \
    --last-buy 2026-05-14 --ex-date 2026-05-15 --record 2026-05-15

  # 데이터 업데이트 뉴스레터 (지급일·분배금액) - GitHub Actions 자동 실행
  python trigger_newsletter.py --type data --timing 월중
"""
import argparse
import json
import os
import sys
import requests
from datetime import datetime
from pathlib import Path

APPS_SCRIPT_URL   = os.environ.get('APPS_SCRIPT_URL', '')
NEWSLETTER_SECRET = os.environ.get('NEWSLETTER_SECRET', '')
LATEST_JSON       = 'data/output/latest.json'
ARCHIVE_JSON      = 'data/output/newsletter/archive.json'
TOP_N             = 15


def save_archive(entry: dict):
    """뉴스레터 발송 내역을 archive.json에 추가 저장"""
    archive_path = Path(ARCHIVE_JSON)
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    archive = []
    if archive_path.exists():
        try:
            with open(archive_path, encoding='utf-8') as f:
                archive = json.load(f)
        except Exception:
            archive = []

    # 동일 id가 이미 있으면 덮어쓰기 (재발송 대응)
    archive = [a for a in archive if a.get('id') != entry['id']]
    archive.append(entry)
    # 날짜 역순 정렬
    archive.sort(key=lambda x: x.get('sent_at', ''), reverse=True)

    with open(archive_path, 'w', encoding='utf-8') as f:
        json.dump(archive, f, ensure_ascii=False, indent=2)
    print(f"아카이브 저장: {ARCHIVE_JSON} (총 {len(archive)}건)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--type',     choices=['schedule', 'data'], default='data',
                        help='schedule: 일정 안내 / data: 분배금액 공시')
    parser.add_argument('--timing',   choices=['월중', '월말'], default=None,
                        help='월중 또는 월말')
    parser.add_argument('--last-buy', dest='last_buy', default=None,
                        help='최종매수일 YYYY-MM-DD (schedule 타입)')
    parser.add_argument('--ex-date',  dest='ex_date',  default=None,
                        help='배당락일 YYYY-MM-DD (schedule 타입)')
    parser.add_argument('--record',   default=None,
                        help='기준일 YYYY-MM-DD (schedule 타입)')
    args = parser.parse_args()

    if not APPS_SCRIPT_URL:
        print("APPS_SCRIPT_URL 없음, 스킵")
        return
    if not NEWSLETTER_SECRET:
        print("NEWSLETTER_SECRET 없음, 스킵")
        return

    now   = datetime.now()
    month = f"{now.year}년 {now.month}월"

    # --timing 미지정 시 날짜로 자동 판단 (20일 이하 → 월중, 21일 이상 → 월말)
    if args.timing:
        timing_label = args.timing
    else:
        timing_label = '월중' if now.day <= 20 else '월말'

    timing_slug = 'mid' if timing_label == '월중' else 'end'
    archive_id  = f"{now.strftime('%Y-%m')}-{timing_slug}-{args.type}"

    # ── 일정 안내 뉴스레터 ─────────────────────────────────────
    if args.type == 'schedule':
        if not all([args.last_buy, args.ex_date, args.record, args.timing]):
            print("schedule 타입에는 --timing --last-buy --ex-date --record 필요")
            sys.exit(1)

        payload = {
            'action':        'send_newsletter',
            'secret':        NEWSLETTER_SECRET,
            'newsletterType': 'schedule',
            'month':         month,
            'timing':        timing_label,
            'lastBuy':       args.last_buy,
            'exDate':        args.ex_date,
            'record':        args.record,
        }

        archive_entry = {
            'id':       archive_id,
            'type':     'schedule',
            'timing':   timing_label,
            'month':    month,
            'sent_at':  now.strftime('%Y-%m-%d'),
            'lastBuy':  args.last_buy,
            'exDate':   args.ex_date,
            'record':   args.record,
        }

    # ── 분배금액 공시 뉴스레터 ─────────────────────────────────
    else:
        try:
            with open(LATEST_JSON, 'r', encoding='utf-8') as f:
                latest = json.load(f)
        except FileNotFoundError:
            print(f"{LATEST_JSON} 없음, 스킵")
            return

        current = [
            e for e in latest
            if e.get('current')
            and e.get('freq') in ('월배당', '월배당추정')
            and e.get('timing') == timing_label
        ]
        current.sort(key=lambda x: float(x.get('rate', 0)), reverse=True)

        etfs = [
            {
                'name':   e['name'],
                'brand':  e['brand'],
                'pay':    e.get('pay_date', e.get('pay', '')),
                'dist':   e['dist'],
                'rate':   e['rate'],
            }
            for e in current[:TOP_N]
        ]

        payload = {
            'action':         'send_newsletter',
            'secret':         NEWSLETTER_SECRET,
            'newsletterType': 'data',
            'month':          month,
            'timing':         timing_label,
            'etfs':           etfs,
        }

        archive_entry = {
            'id':      archive_id,
            'type':    'data',
            'timing':  timing_label,
            'month':   month,
            'sent_at': now.strftime('%Y-%m-%d'),
            'etfs':    etfs,
        }

    print(f"뉴스레터 발송: type={args.type}, timing={timing_label}")
    try:
        r = requests.post(APPS_SCRIPT_URL, json=payload, timeout=60)
        print(f"응답: {r.text}")
    except Exception as e:
        print(f"발송 요청 실패: {e}")
        sys.exit(1)

    # 발송 성공 후 아카이브 저장
    save_archive(archive_entry)


if __name__ == '__main__':
    main()
