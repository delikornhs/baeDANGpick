// sync.js — MY ETF 개인 기기 간 동기화 클라이언트 (관심 ETF + 포트폴리오)
//
// 이 기능은 "개인 패스코드로 로그인한 기기"에서만 동작한다.
// 로그인하지 않은 방문자에게는 window.bdpSync.isEnabled()가 false라
// 네트워크 요청도, 동작 변화도 전혀 없다. (기존 localStorage 방식 그대로)
//
// 동기화 대상 키: bdp_portfolio, bdp_watchlist
// 충돌 처리: updatedAt 타임스탬프 기반 "최신 기기 우선".
//            최초 연결 시 양쪽 모두 데이터가 있으면 사용자에게 선택을 요청.
(function () {
  const META_KEY = 'bdp_sync';        // { token, enabled, updatedAt }
  const PF_KEY   = 'bdp_portfolio';
  const WL_KEY   = 'bdp_watchlist';
  const ENDPOINT = '/api/sync';

  // ── 메타(로그인 상태) ──
  function getMeta() {
    try { return JSON.parse(localStorage.getItem(META_KEY)) || null; } catch { return null; }
  }
  function setMeta(m) { localStorage.setItem(META_KEY, JSON.stringify(m)); }
  function clearMeta() { localStorage.removeItem(META_KEY); }
  function isEnabled() { const m = getMeta(); return !!(m && m.enabled && m.token); }

  // ── 로컬 데이터 ──
  function readArr(k) { try { return JSON.parse(localStorage.getItem(k) || '[]'); } catch { return []; } }
  function snapshot() { return { portfolio: readArr(PF_KEY), watchlist: readArr(WL_KEY) }; }
  function hasLocalData() { const s = snapshot(); return s.portfolio.length > 0 || s.watchlist.length > 0; }
  function applySnapshot(d) {
    if (!d) return;
    if (Array.isArray(d.portfolio)) localStorage.setItem(PF_KEY, JSON.stringify(d.portfolio));
    if (Array.isArray(d.watchlist)) localStorage.setItem(WL_KEY, JSON.stringify(d.watchlist));
  }

  // ── 서버 호출 ──
  async function call(op, body) {
    const res = await fetch(ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ op, ...body }),
    });
    let json = {};
    try { json = await res.json(); } catch {}
    return { status: res.status, ok: res.ok, body: json };
  }

  // ── 상태 콜백 (UI 표시용) ──
  let statusCb = null;
  function onStatus(cb) { statusCb = cb; }
  function mark(s) { if (statusCb) { try { statusCb(s); } catch {} } }

  // ── 변경 시 클라우드로 올리기 (디바운스) ──
  let pushTimer = null;
  function push() {
    if (!isEnabled()) return;
    const m = getMeta();
    m.updatedAt = Date.now();
    setMeta(m);
    mark('saving');
    clearTimeout(pushTimer);
    pushTimer = setTimeout(async () => {
      try {
        const r = await call('push', { secret: m.token, data: snapshot(), updatedAt: m.updatedAt });
        mark(r.ok ? 'saved' : 'error');
      } catch (e) { console.warn('[sync] push 실패', e); mark('error'); }
    }, 700);
  }

  // ── 페이지 로드 시 클라우드에서 내려받기 ──
  async function pull(onAdopt) {
    if (!isEnabled()) return;
    const m = getMeta();
    try {
      const r = await call('pull', { secret: m.token });
      if (r.status === 401) { mark('unauthorized'); return; }
      if (!r.ok) { mark('error'); return; }
      const cloudTs = r.body.updatedAt || 0;
      const localTs = m.updatedAt || 0;
      if (r.body.data && cloudTs > localTs) {
        applySnapshot(r.body.data);       // 클라우드가 더 최신 → 내려받아 반영
        m.updatedAt = cloudTs;
        setMeta(m);
        mark('synced');
        if (typeof onAdopt === 'function') onAdopt();
      } else if (localTs > cloudTs) {
        push();                           // 로컬이 더 최신 → 올림 (오프라인 변경·push 실패 복구)
      } else {
        mark('synced');                   // 동일 → 할 일 없음
      }
    } catch (e) { console.warn('[sync] pull 실패', e); mark('error'); }
  }

  // ── 최초 연결(로그인) ──
  // 반환:
  //   { result:'unauthorized' }                          패스코드 틀림
  //   { result:'error', message }                        서버/네트워크 오류
  //   { result:'need-choice', token, cloud, cloudTs }    양쪽 다 데이터 → 선택 필요
  //   { result:'linked', adopted:'cloud'|'local'|'empty' } 연결 완료
  async function link(token) {
    const r = await call('pull', { secret: token });
    if (r.status === 401) return { result: 'unauthorized' };
    if (!r.ok) return { result: 'error', message: (r.body && r.body.error) || '연결 실패' };

    const cloud   = r.body.data;
    const cloudTs = r.body.updatedAt || 0;
    const cloudHas = !!(cloud && ((cloud.portfolio || []).length || (cloud.watchlist || []).length));
    const localHas = hasLocalData();

    if (cloudHas && localHas) return { result: 'need-choice', token, cloud, cloudTs };

    if (cloudHas) {
      applySnapshot(cloud);
      setMeta({ token, enabled: true, updatedAt: cloudTs });
      mark('synced');
      return { result: 'linked', adopted: 'cloud' };
    }

    // 클라우드 비어있음 → 로컬 올리기 (로컬도 비면 빈 상태로 연결)
    const now = Date.now();
    setMeta({ token, enabled: true, updatedAt: now });
    try { await call('push', { secret: token, data: snapshot(), updatedAt: now }); } catch {}
    mark('synced');
    return { result: 'linked', adopted: localHas ? 'local' : 'empty' };
  }

  // need-choice 이후 사용자가 고른 쪽으로 확정
  async function resolveChoice(token, choice, cloud, cloudTs) {
    if (choice === 'cloud') {
      applySnapshot(cloud);
      setMeta({ token, enabled: true, updatedAt: cloudTs || Date.now() });
      mark('synced');
      return { adopted: 'cloud' };
    }
    const now = Date.now();
    setMeta({ token, enabled: true, updatedAt: now });
    try { await call('push', { secret: token, data: snapshot(), updatedAt: now }); } catch {}
    mark('synced');
    return { adopted: 'local' };
  }

  function unlink() { clearMeta(); mark('off'); }

  window.bdpSync = {
    isEnabled, getMeta, snapshot,
    push, pull, link, resolveChoice, unlink, onStatus,
  };
})();
