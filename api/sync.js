// api/sync.js — MY ETF 개인 기기 간 동기화 (Upstash Redis 백엔드, 패스코드 잠금)
//
// 필요한 Vercel 환경변수:
//   SYNC_SECRET                                        개인 패스코드 (내가 정한 값)
//   KV_REST_API_URL / KV_REST_API_TOKEN                (Vercel KV 명칭)          또는
//   UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN  (Upstash 직접 통합 명칭)
//
// 저장 구조: 단일 키에 { data:{portfolio,watchlist}, updatedAt } JSON 한 덩어리.
// 사용자가 사실상 한 명이므로 키는 고정. 패스코드를 아는 사람만 읽고 쓸 수 있다.

const KEY = 'bdp:myetf';

function redisEnv() {
  const url   = process.env.KV_REST_API_URL   || process.env.UPSTASH_REDIS_REST_URL;
  const token = process.env.KV_REST_API_TOKEN || process.env.UPSTASH_REDIS_REST_TOKEN;
  return { url, token };
}

async function redis(cmd) {
  const { url, token } = redisEnv();
  if (!url || !token) throw new Error('KV 저장소 환경변수가 설정되지 않았습니다');
  const res = await fetch(url, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(cmd),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error) throw new Error(data.error || `Redis 오류 ${res.status}`);
  return data.result;
}

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const { secret, op, data, updatedAt } = req.body || {};

  if (!process.env.SYNC_SECRET) {
    return res.status(500).json({ error: '동기화가 아직 설정되지 않았습니다 (SYNC_SECRET 없음)' });
  }
  if (!secret || secret !== process.env.SYNC_SECRET) {
    return res.status(401).json({ error: '패스코드가 올바르지 않습니다' });
  }

  try {
    if (op === 'pull') {
      const raw = await redis(['GET', KEY]);
      if (!raw) return res.status(200).json({ ok: true, data: null, updatedAt: 0 });
      let parsed = null;
      try { parsed = JSON.parse(raw); } catch {}
      return res.status(200).json({
        ok: true,
        data:      parsed ? (parsed.data || null) : null,
        updatedAt: parsed ? (parsed.updatedAt || 0) : 0,
      });
    }

    if (op === 'push') {
      const ts = updatedAt || Date.now();
      await redis(['SET', KEY, JSON.stringify({ data: data || null, updatedAt: ts })]);
      return res.status(200).json({ ok: true, updatedAt: ts });
    }

    return res.status(400).json({ error: 'op은 pull 또는 push 여야 합니다' });
  } catch (e) {
    console.error(e);
    return res.status(500).json({ error: e.message });
  }
}
