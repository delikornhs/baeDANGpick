"""
자동 반영·발송 스크립트(auto_schedule.py, auto_data_newsletter.py) 공용 도구.

■ 안전 원칙
  - 실제 발송·push는 GitHub Actions 안에서 --live 를 줬을 때만 한다.
    로컬에서 --live 를 줘도 거부한다 — 사람 PC에서 실수로 구독자에게 나가는 일을 막는다.
  - 발송 여부의 기준은 newsletter/archive.json 하나다. 같은 id가 있으면 다시 보내지 않는다.
  - push가 거부되면 원격 최신본 위에 우리 변경만 다시 적용해 재시도한다.
    남의 커밋을 덮는 충돌 해결(--ours/--theirs)은 쓰지 않는다.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
ARCHIVE_JSON = Path("data/output/newsletter/archive.json")


def now_kst() -> datetime:
    return datetime.now(KST)


def in_ci() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def resolve_live(requested: bool) -> bool:
    if requested and not in_ci():
        print("⚠️ --live 는 GitHub Actions 안에서만 동작합니다 — 이번 실행은 점검(dry-run)으로 진행합니다.")
        return False
    return requested


# ── 발송 기록 ────────────────────────────────────────────────

def archive_ids() -> set:
    try:
        with open(ARCHIVE_JSON, encoding="utf-8") as f:
            return {a.get("id") for a in json.load(f)}
    except (OSError, ValueError):
        return set()


def archive_entry(aid: str):
    try:
        with open(ARCHIVE_JSON, encoding="utf-8") as f:
            return next((a for a in json.load(f) if a.get("id") == aid), None)
    except (OSError, ValueError):
        return None


def merge_archive_entry(entry: dict) -> bool:
    """원격 최신 archive.json에 우리 항목을 다시 넣는다(push 재시도용). 이미 있으면 False."""
    try:
        with open(ARCHIVE_JSON, encoding="utf-8") as f:
            archive = json.load(f)
    except (OSError, ValueError):
        archive = []
    if any(a.get("id") == entry.get("id") for a in archive):
        return False
    archive.append(entry)
    archive.sort(key=lambda x: x.get("sent_at", ""), reverse=True)
    with open(ARCHIVE_JSON, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, indent=2)
    return True


# ── git ─────────────────────────────────────────────────────

def _git(*args, check=True):
    r = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 실패: {r.stderr.strip() or r.stdout.strip()}")
    return r


def commit_and_push(paths: list, message: str, reapply, attempts: int = 4) -> str:
    """paths만 커밋해 master로 push한다.

    거부되면 원격 최신본으로 되돌린 뒤 reapply()로 우리 변경을 다시 만들고 재시도한다.
    reapply()가 False를 돌려주면 원격에 이미 반영된 것으로 보고 멈춘다.
    반환: 'pushed' | 'nochange' | 'already'
    """
    for i in range(attempts):
        _git("add", *paths)
        if _git("diff", "--cached", "--quiet", check=False).returncode == 0:
            return "nochange"
        _git("commit", "-m", message)
        if _git("push", "origin", "HEAD:master", check=False).returncode == 0:
            return "pushed"

        print(f"   push 거부 — 원격 최신본 위에 다시 적용합니다 ({i + 1}/{attempts})")
        _git("fetch", "origin", "master")
        ahead = int(_git("rev-list", "--count", "origin/master..HEAD").stdout.strip())
        if ahead != 1:
            # 우리 커밋 말고도 push 안 된 커밋이 있다 — 되돌리면 그것까지 잃으므로 멈춘다
            raise RuntimeError(f"push 안 된 커밋이 {ahead}개라 자동 재시도를 중단합니다")
        _git("reset", "--hard", "origin/master")
        if not reapply():
            return "already"
    raise RuntimeError(f"push {attempts}회 실패")


# ── 뉴스레터 발송 ────────────────────────────────────────────

def send_newsletter(args: list):
    """trigger_newsletter.py 실행. 반환: (종료코드, 출력)

    0 = 발송 성공(아카이브 기록됨)
    1 = 발송 안 됨(아카이브 기록 안 됨) — 재시도해도 중복 위험 없음
    2 = 결과 불명(아카이브에 '미확인'으로 기록됨) — 중복을 막기 위해 재시도하지 않는다
    """
    r = subprocess.run([sys.executable, "-X", "utf8", "trigger_newsletter.py", *args],
                       capture_output=True, text=True, encoding="utf-8")
    out = (r.stdout or "") + (r.stderr or "")
    print(out.rstrip())
    return r.returncode, out


# ── 결과 보고 ───────────────────────────────────────────────

def write_report(name: str, status: str, title: str, lines: list):
    """워크플로가 이슈를 만들 때 읽는 보고서와 상태를 남긴다.

    status: done(처리 완료) | nothing(할 일 없음) | waiting(다음 실행에 재시도) | held(사람 확인 필요)
    """
    Path(f"{name}_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    Path(f"{name}_title.txt").write_text(title, encoding="utf-8")
    print(f"\nAUTO_STATUS={status}")
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"status={status}\n")


def commit_new_archive_entries(message: str) -> str:
    """로컬 archive.json에 새로 생긴 항목만 골라 커밋·push한다(수동 발송 워크플로용).

    push가 거부되면 원격 최신본에 새 항목을 합쳐 다시 시도한다. 예전 워크플로는 리베이스
    충돌을 --ours로 풀었는데, 리베이스 중 --ours는 원격 쪽이라 방금 보낸 기록이 버려졌다.
    기록이 사라지면 자동 발송이 그 회차를 '안 보낸 것'으로 보고 다시 보낼 수 있다.
    """
    head = _git("show", f"HEAD:{ARCHIVE_JSON.as_posix()}", check=False).stdout
    head_ids = {a.get("id") for a in (json.loads(head) if head.strip() else [])}
    try:
        with open(ARCHIVE_JSON, encoding="utf-8") as f:
            local = json.load(f)
    except (OSError, ValueError):
        local = []
    new = [a for a in local if a.get("id") not in head_ids]
    if not new:
        print("아카이브 변경 없음")
        return "nochange"
    print(f"새 아카이브 항목: {[a.get('id') for a in new]}")
    return commit_and_push([ARCHIVE_JSON.as_posix()], message,
                           lambda: any([merge_archive_entry(e) for e in new]))


if __name__ == "__main__":
    # python auto_common.py commit-archive "커밋 메시지"
    if len(sys.argv) == 3 and sys.argv[1] == "commit-archive":
        if not in_ci():
            sys.exit("GitHub Actions 안에서만 실행합니다 (push 실패 시 로컬 변경을 되돌리기 때문)")
        print(commit_new_archive_entries(sys.argv[2]))
    else:
        sys.exit('사용법: python auto_common.py commit-archive "커밋 메시지"')
