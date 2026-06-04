// api/publish.js — 인사이트 글 게시 서버리스 함수
// Vercel 환경변수 필요: GITHUB_TOKEN, ADMIN_SECRET

const OWNER  = 'delikornhs';
const REPO   = 'baeDANGpick';
const BRANCH = 'master';

async function githubRequest(path, method, body) {
  const res = await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/contents/${path}`, {
    method,
    headers: {
      Authorization: `token ${process.env.GITHUB_TOKEN}`,
      'Content-Type': 'application/json',
      Accept: 'application/vnd.github.v3+json',
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.message || `GitHub API error ${res.status}`);
  return data;
}

async function getFileSha(path) {
  try {
    const data = await githubRequest(path, 'GET');
    return { sha: data.sha, content: Buffer.from(data.content, 'base64').toString('utf-8') };
  } catch {
    return { sha: null, content: null };
  }
}

function slugify(title) {
  return title
    .replace(/[^가-힣a-zA-Z0-9\s]/g, '')
    .trim()
    .replace(/\s+/g, '-')
    .slice(0, 40)
    .toLowerCase();
}

function buildPostHtml({ title, date, category, summary, content }) {
  return `<!DOCTYPE html>
<html lang="ko">
<head>
<script async src="https://www.googletagmanager.com/gtag/js?id=G-70RCL5E7B8"><\/script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','G-70RCL5E7B8');<\/script>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${title} - 배당픽 인사이트</title>
<meta name="description" content="${summary}">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#f7f7f4;--white:#fff;--ink:#1a1a18;--ink2:#4a4a45;--ink3:#9a9a93;--ink4:#d4d4cc;--accent:#1d6b38;--accent-bg:#edf7f1;--accent-mid:#6cba8b;--warn:#b45309;--warn-bg:#fffbeb;--red:#dc2626;--border:#e8e8e2;--radius:10px}
body{background:var(--bg);color:var(--ink);font-family:"Noto Sans KR",sans-serif;min-height:100vh;line-height:1.8}
nav{background:var(--white);border-bottom:1px solid var(--border);padding:0 20px;position:sticky;top:0;z-index:200}
.nav-inner{max-width:1100px;margin:0 auto;height:52px;display:flex;align-items:center;justify-content:space-between}
.logo{font-size:15px;font-weight:700;letter-spacing:-.4px;display:flex;align-items:center;gap:7px;text-decoration:none;color:var(--ink)}
.logo-mark{width:22px;height:22px;background:var(--accent);border-radius:5px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:11px;font-weight:700}
.nav-links{display:flex;gap:6px;align-items:center}
.nav-link{font-size:12px;color:var(--ink2);text-decoration:none;font-weight:600;padding:5px 12px;border-radius:6px;border:1px solid var(--border);background:var(--bg);transition:all .15s;white-space:nowrap}
.nav-link:hover{color:var(--accent);border-color:var(--accent-mid);background:var(--accent-bg)}
.nav-link.on{color:var(--accent);border-color:var(--accent);background:var(--accent-bg)}
.post-wrap{max-width:720px;margin:0 auto;padding:48px 20px 80px}
.post-back{display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--ink3);text-decoration:none;margin-bottom:28px;transition:color .15s}
.post-back:hover{color:var(--accent)}
.post-category{display:inline-block;font-size:11px;font-weight:700;color:var(--accent);background:var(--accent-bg);padding:3px 8px;border-radius:4px;margin-bottom:14px}
.post-title{font-size:26px;font-weight:700;letter-spacing:-.6px;line-height:1.4;margin-bottom:10px}
.post-date{font-size:12px;color:var(--ink3);margin-bottom:36px;padding-bottom:24px;border-bottom:1px solid var(--border)}
.post-body h2{font-size:19px;font-weight:700;letter-spacing:-.3px;margin:40px 0 14px;padding-left:12px;border-left:3px solid var(--accent)}
.post-body h3{font-size:16px;font-weight:700;margin:24px 0 10px;color:var(--ink)}
.post-body p{font-size:15px;color:var(--ink2);margin-bottom:16px;line-height:1.85}
.post-body p strong{color:var(--ink);font-weight:700}
.post-body table{width:100%;border-collapse:collapse;margin:14px 0 20px;font-size:13px}
.post-body th{background:var(--accent-bg);color:var(--accent);font-weight:700;padding:9px 12px;border:1px solid var(--border);text-align:left}
.post-body td{padding:8px 12px;border:1px solid var(--border);color:var(--ink2)}
.post-body tr:nth-child(even) td{background:#fafaf8}
.post-body hr{border:none;border-top:1px solid var(--border);margin:36px 0}
.post-body ul,.post-body ol{padding-left:20px;margin-bottom:16px}
.post-body li{font-size:15px;color:var(--ink2);line-height:1.85}
.post-body blockquote{border-left:3px solid var(--accent-mid);padding:10px 16px;margin:16px 0;background:var(--accent-bg);border-radius:0 6px 6px 0}
.post-body blockquote p{color:var(--ink2);margin-bottom:0}
.notice{background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);padding:14px 18px;margin:32px 0 0;font-size:12px;color:var(--ink3);line-height:1.7}
footer{text-align:center;padding:24px 20px;font-size:12px;color:var(--ink3);border-top:1px solid var(--border);background:var(--white);line-height:1.8}
footer a{color:var(--ink3);text-underline-offset:2px}
@media(max-width:600px){.post-title{font-size:21px}.nav-links{gap:4px}.nav-link{font-size:11px;padding:4px 8px}.post-body table{font-size:12px}}
.pf-fab{position:fixed;bottom:24px;right:24px;z-index:500;background:var(--accent);color:#fff;border:none;border-radius:50px;padding:12px 20px;font-size:13px;font-weight:700;box-shadow:0 4px 16px rgba(29,107,56,.3);display:flex;align-items:center;gap:7px;text-decoration:none;transition:all .2s;font-family:"Noto Sans KR",sans-serif;white-space:nowrap}
.pf-fab:hover{background:#165a2e;transform:translateY(-2px)}
</style>
</head>
<body>
<nav>
  <div class="nav-inner">
    <a href="/" class="logo"><div class="logo-mark">&#8361;</div>배당픽</a>
    <div class="nav-links">
      <a href="/ranking.html" class="nav-link">랭킹</a>
      <a href="/calc.html" class="nav-link">계산기</a>
      <a href="/insight.html" class="nav-link on">인사이트</a>
      <a href="/newsletter.html" class="nav-link">뉴스레터</a>
    </div>
  </div>
</nav>
<div class="post-wrap">
  <a href="/insight.html" class="post-back">← 인사이트 목록</a>
  <div class="post-category">${category}</div>
  <h1 class="post-title">${title}</h1>
  <p class="post-date">${date}</p>
  <div class="post-body">
${content}
    <div class="notice">본 분석은 배당픽 데이터를 기반으로 작성되었으며, 투자 권유가 아닙니다. 분석에서 언급된 ETF 상품명은 데이터 설명을 위한 예시로 활용된 것으로, 특정 상품에 대한 매수 추천 또는 매도 권유가 아닙니다. 최종 투자 판단은 본인에게 있습니다.</div>
  </div>
</div>
<footer>
  본 사이트의 정보는 참고 목적으로만 제공되며, 투자의 최종 판단은 본인에게 있습니다.<br>
  <a href="https://docs.google.com/forms/d/e/1FAIpQLSflCQap_v_YXjEwRVnjiaQhh9Nkppmw0HWK8YQ1HzR7lAKf9g/viewform?usp=publish-editor" target="_blank" rel="noopener">오류 및 개선 의견 보내기</a>
  &nbsp;·&nbsp;<a href="/privacy.html">개인정보처리방침</a>
</footer>
<a href="/portfolio.html" class="pf-fab">⭐ <span>MY ETF</span></a>
</body>
</html>`;
}

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const { secret, title, date, category, summary, content } = req.body || {};

  // 인증
  if (!process.env.ADMIN_SECRET || secret !== process.env.ADMIN_SECRET) {
    return res.status(401).json({ error: '인증 실패' });
  }
  if (!title || !date || !category || !content) {
    return res.status(400).json({ error: '필수 항목 누락' });
  }
  if (!process.env.GITHUB_TOKEN) {
    return res.status(500).json({ error: 'GITHUB_TOKEN 없음' });
  }

  try {
    const slug    = `${date}-${slugify(title)}`;
    const filePath = `insight/posts/${slug}.html`;
    const postHtml = buildPostHtml({ title, date, category, summary: summary || '', content });

    // 1. 글 파일 생성
    const { sha: existSha } = await getFileSha(filePath);
    await githubRequest(filePath, 'PUT', {
      message: `새 글: ${title}`,
      content: Buffer.from(postHtml).toString('base64'),
      branch: BRANCH,
      ...(existSha ? { sha: existSha } : {}),
    });

    // 2. posts.json 업데이트
    const postsPath = 'insight/posts.json';
    const { sha: postsSha, content: postsRaw } = await getFileSha(postsPath);
    let posts = [];
    if (postsRaw) {
      try { posts = JSON.parse(postsRaw); } catch {}
    }

    // 동일 id 있으면 교체, 없으면 맨 앞에 추가
    const newEntry = { id: slug, title, date, category, summary: summary || '', file: filePath };
    posts = posts.filter(p => p.id !== slug);
    posts.unshift(newEntry);
    // 날짜 내림차순 정렬 (가이드는 맨 뒤)
    posts.sort((a, b) => {
      if (a.category === '가이드' && b.category !== '가이드') return 1;
      if (a.category !== '가이드' && b.category === '가이드') return -1;
      return b.date.localeCompare(a.date);
    });

    await githubRequest(postsPath, 'PUT', {
      message: `posts.json 업데이트: ${title}`,
      content: Buffer.from(JSON.stringify(posts, null, 2)).toString('base64'),
      branch: BRANCH,
      sha: postsSha,
    });

    res.status(200).json({ ok: true, file: filePath, slug });
  } catch (e) {
    console.error(e);
    res.status(500).json({ error: e.message });
  }
}
