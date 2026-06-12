// ================================================================
// 배당픽 뉴스레터 구독 - Google Apps Script
//
// [Script Properties 설정 필요] Apps Script → 프로젝트 설정 → 스크립트 속성
//   NEWSLETTER_SECRET : baeDangpick2026
//
// [시트 구조] '구독자' 시트
//   A: 가입일시  B: 이메일  C: 토큰  D: 상태  E: 출처  F: 동의여부  G: watchlist
//
// [배포] 배포 관리 → 연필 아이콘 → 버전: 새 버전으로 교체
// ================================================================

const SHEET_NAME        = '구독자';
const SENDER_NAME       = '배당픽';
const NEWSLETTER_SECRET = 'baeDangpick2026';

// 열 인덱스 (0-based, getValues() 기준)
// A=0: 가입일시  B=1: 이메일  C=2: 토큰  D=3: 상태  E=4: 출처  F=5: 동의여부  G=6: watchlist


// ── GET: 수신거부 처리 ──────────────────────────────────────────
function doGet(e) {
  const action = (e.parameter.action || '').trim();
  if (action === 'unsubscribe') {
    return handleUnsubscribe(e.parameter.token || '');
  }
  return HtmlService.createHtmlOutput('<p>배당픽 구독 서비스입니다.</p>');
}


// ── POST: 구독 신청 / 뉴스레터 발송 트리거 ────────────────────
function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);
    if (data.action === 'send_newsletter') {
      return handleSendNewsletter(data);
    }
    return handleSubscribe(data);
  } catch (err) {
    return jsonResponse({ result: 'error', message: err.message });
  }
}


// ── 구독 신청 ──────────────────────────────────────────────────
function handleSubscribe(data) {
  const email    = (data.email || '').trim().toLowerCase();
  const watchlist = data.watchlist || [];  // 관심 ETF 코드 배열

  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return jsonResponse({ result: 'error', message: '이메일 형식 오류' });
  }

  const sheet    = getOrCreateSheet();
  const existRow = findSubscriberRow(sheet, email);

  // 이미 등록된 이메일 → watchlist만 업데이트
  if (existRow) {
    sheet.getRange(existRow, 7).setValue(watchlist.join(','));
    return jsonResponse({ result: 'updated', message: '관심 ETF가 업데이트되었습니다.' });
  }

  // 신규 등록
  const token     = Utilities.getUuid();
  const scriptUrl = ScriptApp.getService().getUrl();

  sheet.appendRow([
    new Date(),                // A: 가입일시
    email,                     // B: 이메일
    token,                     // C: 토큰
    '활성',                    // D: 상태
    data.source    || 'web',   // E: 출처
    data.consented ? '동의' : '미동의', // F: 동의여부
    watchlist.join(','),       // G: watchlist
  ]);

  sendWelcomeEmail(email, token, scriptUrl);
  return jsonResponse({ result: 'success' });
}


// ── 수신거부 ───────────────────────────────────────────────────
function handleUnsubscribe(token) {
  const sheet = getOrCreateSheet();
  const rows  = sheet.getDataRange().getValues();

  for (let i = 1; i < rows.length; i++) {
    if (rows[i][2] === token) {
      sheet.getRange(i + 1, 4).setValue('해지');
      return HtmlService.createHtmlOutput(`
        <html><body style="font-family:sans-serif;text-align:center;padding:60px 20px">
          <h2 style="color:#1d6b38">수신 거부 완료</h2>
          <p style="color:#555">배당픽 뉴스레터 수신이 해지되었습니다.</p>
          <a href="https://baedangetf.com"
             style="display:inline-block;margin-top:20px;background:#1d6b38;color:#fff;
                    padding:10px 24px;border-radius:7px;text-decoration:none;font-size:14px">
            배당픽 바로가기
          </a>
        </body></html>`);
    }
  }
  return HtmlService.createHtmlOutput('<p>유효하지 않은 링크입니다.</p>');
}


// ── 뉴스레터 발송 (GitHub Actions 트리거) ──────────────────────
function handleSendNewsletter(data) {
  if (!NEWSLETTER_SECRET || data.secret !== NEWSLETTER_SECRET) {
    return jsonResponse({ result: 'error', message: 'unauthorized' });
  }

  const sheet     = getOrCreateSheet();
  const rows      = sheet.getDataRange().getValues();
  const scriptUrl = ScriptApp.getService().getUrl();

  const month          = data.month          || '';
  const timing         = data.timing         || '';
  const newsletterType = data.newsletterType || 'data';

  const subject = newsletterType === 'schedule'
    ? `[배당픽] ${month} ${timing} 배당 주요 일정 안내`
    : `[배당픽] ${month} ${timing} 분배금액 공시`;

  let sent = 0, failed = 0;

  for (let i = 1; i < rows.length; i++) {
    const email    = rows[i][1];
    const token    = rows[i][2];
    const status   = rows[i][3];
    const watchlist = rows[i][6]
      ? String(rows[i][6]).split(',').map(s => s.trim()).filter(Boolean)
      : [];

    if (status !== '활성') continue;

    try {
      const html = newsletterType === 'schedule'
        ? buildScheduleNewsletterHtml(data, watchlist, scriptUrl, token)
        : buildDataNewsletterHtml(data, watchlist, scriptUrl, token);

      MailApp.sendEmail({ to: email, subject: subject, htmlBody: html, name: SENDER_NAME });
      sent++;
      Utilities.sleep(300);
    } catch (err) {
      Logger.log(`발송 실패 ${email}: ${err.message}`);
      failed++;
    }
  }

  Logger.log(`뉴스레터 발송 완료 - 성공: ${sent}, 실패: ${failed}`);
  return jsonResponse({ result: 'success', sent: sent, failed: failed });
}


// ── 환영 이메일 ────────────────────────────────────────────────
function sendWelcomeEmail(email, token, scriptUrl) {
  const unsubUrl = `${scriptUrl}?action=unsubscribe&token=${token}`;
  MailApp.sendEmail({
    to:       email,
    subject:  '[배당픽] 뉴스레터 구독이 완료되었습니다',
    name:     SENDER_NAME,
    htmlBody: `
    <div style="font-family:sans-serif;max-width:520px;margin:0 auto;padding:20px">
      <div style="background:#1d6b38;border-radius:10px 10px 0 0;padding:20px 24px">
        <span style="color:#fff;font-size:17px;font-weight:700">배당픽</span>
      </div>
      <div style="border:1px solid #e8e8e2;border-top:none;border-radius:0 0 10px 10px;padding:28px 24px">
        <h2 style="color:#1d6b38;margin:0 0 12px">구독 완료!</h2>
        <p style="color:#444;line-height:1.7;margin:0 0 20px">
          매월 ETF 분배금 일정(배당락일·지급일·분배금액)을 월 2회 이메일로 안내해 드립니다.<br>
          관심 ETF를 등록하셨다면 해당 ETF 중심으로 맞춤 뉴스레터를 드립니다.
        </p>
        <a href="https://baedangetf.com"
           style="display:inline-block;background:#1d6b38;color:#fff;text-decoration:none;
                  font-size:14px;font-weight:700;padding:12px 28px;border-radius:7px">
          배당픽 바로가기 →
        </a>
        <hr style="margin:28px 0 16px;border:none;border-top:1px solid #eee">
        <p style="font-size:11px;color:#aaa;margin:0">
          수신을 원하지 않으시면 <a href="${unsubUrl}" style="color:#aaa">여기</a>를 클릭해 수신거부 하세요.
        </p>
      </div>
    </div>`
  });
}


// ── 일정 안내 뉴스레터 빌더 ────────────────────────────────────
function buildScheduleNewsletterHtml(data, watchlist, scriptUrl, token) {
  const { month, timing, lastBuy, exDate, record, timingEtfs = [] } = data;
  const unsubUrl = `${scriptUrl}?action=unsubscribe&token=${token}`;

  // 관심 ETF 중 이번 timing에 해당하는 것
  const myEtfs = watchlist.length
    ? timingEtfs.filter(e => watchlist.includes(e.code))
    : [];

  // 관심 ETF 섹션 HTML
  let myEtfSection = '';
  if (myEtfs.length) {
    const names = myEtfs.map(e =>
      `<div style="font-size:13px;color:#1a1a18;padding:4px 0;border-bottom:1px solid #e8f5ee">
         <span style="color:#1d6b38;font-weight:700">·</span> ${e.name}
         <span style="font-size:11px;color:#9a9a93;margin-left:4px">${e.brand || ''}</span>
       </div>`
    ).join('');
    myEtfSection = `
      <div style="background:#edf7f1;border-radius:8px;padding:16px 20px;margin-bottom:24px">
        <div style="font-size:13px;font-weight:700;color:#1d6b38;margin-bottom:10px">
          ⭐ 내 관심 ETF — 이번 ${timing} 배당 대상
        </div>
        ${names}
      </div>`;
  }

  return `<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f7f7f4;font-family:'Apple SD Gothic Neo',sans-serif">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td style="padding:24px 16px">
<table width="100%" style="max-width:600px;margin:0 auto;background:#fff;
  border-radius:12px;overflow:hidden;border:1px solid #e8e8e2">

  <tr><td style="background:#1d6b38;padding:20px 28px">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td style="color:#fff;font-size:17px;font-weight:700">배당픽</td>
      <td style="text-align:right;color:rgba(255,255,255,.7);font-size:12px">${month} ${timing}</td>
    </tr></table>
  </td></tr>

  <tr><td style="padding:24px 28px 8px">
    <div style="font-size:18px;font-weight:700;color:#1a1a18;margin-bottom:6px">
      ${month} ${timing} 배당 주요 일정이 확정되었습니다
    </div>
    <div style="font-size:12px;color:#9a9a93;margin-bottom:24px">
      분배금액은 공시 후 별도 안내드립니다
    </div>

    ${myEtfSection}

    <div style="font-size:13px;font-weight:700;color:#1a1a18;margin-bottom:10px">📅 배당 일정</div>
    <table width="100%" cellpadding="0" cellspacing="0"
      style="border:1px solid #e8e8e2;border-radius:8px;overflow:hidden;border-collapse:collapse">
      <tr style="background:#edf7f1">
        <th style="padding:11px 16px;font-size:12px;color:#1d6b38;text-align:left;font-weight:700">일정</th>
        <th style="padding:11px 16px;font-size:12px;color:#1d6b38;text-align:center;font-weight:700">날짜</th>
      </tr>
      <tr>
        <td style="padding:11px 16px;border-bottom:1px solid #f0f0f0;
          font-size:13px;color:#1a1a18;font-weight:700">🛒 최종 매수일</td>
        <td style="padding:11px 16px;border-bottom:1px solid #f0f0f0;
          font-size:13px;text-align:center;color:#1d6b38;font-weight:700;
          font-family:monospace">${lastBuy}</td>
      </tr>
      <tr>
        <td style="padding:11px 16px;border-bottom:1px solid #f0f0f0;
          font-size:13px;color:#1a1a18">📉 배당락일</td>
        <td style="padding:11px 16px;border-bottom:1px solid #f0f0f0;
          font-size:13px;text-align:center;color:#4a4a45;
          font-family:monospace">${exDate}</td>
      </tr>
      <tr>
        <td style="padding:11px 16px;font-size:13px;color:#1a1a18">📋 기준일</td>
        <td style="padding:11px 16px;font-size:13px;text-align:center;
          color:#4a4a45;font-family:monospace">${record}</td>
      </tr>
    </table>
    <p style="font-size:12px;color:#9a9a93;margin-top:12px;line-height:1.7">
      ※ <strong style="color:#1d6b38">${lastBuy}</strong>까지 매수해야 이번 달 분배금을 받을 수 있습니다.
    </p>
  </td></tr>

  <tr><td style="padding:8px 28px 28px;text-align:center">
    <a href="https://baedangetf.com"
       style="display:inline-block;background:#1d6b38;color:#fff;text-decoration:none;
              font-size:14px;font-weight:700;padding:13px 32px;border-radius:8px">
      전체 일정 확인하기 →
    </a>
  </td></tr>

  <tr><td style="background:#f7f7f4;padding:16px 28px;border-top:1px solid #e8e8e2;text-align:center">
    <p style="font-size:11px;color:#9a9a93;margin:0;line-height:1.8">
      본 정보는 참고 목적으로만 제공되며 투자의 최종 판단은 본인에게 있습니다.<br>
      <a href="${unsubUrl}" style="color:#9a9a93;text-decoration:underline">수신거부</a>
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body></html>`;
}


// ── 분배금 공시 뉴스레터 빌더 ──────────────────────────────────
function buildDataNewsletterHtml(data, watchlist, scriptUrl, token) {
  const { month, timing, etfs = [] } = data;
  const unsubUrl = `${scriptUrl}?action=unsubscribe&token=${token}`;

  // 관심 ETF 중 이번 데이터에 있는 것
  const myEtfs    = watchlist.length ? etfs.filter(e => watchlist.includes(e.code)) : [];
  // 나머지 전체 (관심 ETF 없으면 전체 표시)
  const otherEtfs = myEtfs.length   ? etfs.filter(e => !watchlist.includes(e.code)) : etfs;

  // ETF 테이블 HTML 생성 헬퍼
  function etfRows(list) {
    return list.slice(0, 15).map((e, i) => `
      <tr>
        <td style="padding:9px 8px;border-bottom:1px solid #f0f0f0;
          font-size:12px;color:#9a9a93;text-align:center;width:24px">${i + 1}</td>
        <td style="padding:9px 8px;border-bottom:1px solid #f0f0f0">
          <div style="font-size:13px;font-weight:600;color:#1a1a18;line-height:1.3">${e.name}</div>
          <div style="font-size:11px;color:#9a9a93;margin-top:2px">${e.brand || ''}</div>
        </td>
        <td style="padding:9px 8px;border-bottom:1px solid #f0f0f0;
          font-size:13px;font-weight:700;color:#1a1a18;text-align:right;white-space:nowrap">
          ${Number(e.dist).toLocaleString('ko-KR')}원</td>
        <td style="padding:9px 8px;border-bottom:1px solid #f0f0f0;
          font-size:13px;font-weight:700;color:#1d6b38;text-align:right;white-space:nowrap">
          ${parseFloat(e.rate).toFixed(2)}%</td>
        <td style="padding:9px 8px;border-bottom:1px solid #f0f0f0;
          font-size:11px;color:#9a9a93;text-align:right;white-space:nowrap">
          ${fmtDate(e.pay)}</td>
      </tr>`).join('');
  }

  function etfTable(list) {
    if (!list.length) return '';
    return `
      <table width="100%" cellpadding="0" cellspacing="0"
        style="border:1px solid #e8e8e2;border-radius:8px;overflow:hidden;border-collapse:collapse">
        <thead>
          <tr style="background:#f7f7f4">
            <th style="padding:7px 8px;font-size:11px;color:#9a9a93;font-weight:600;text-align:center"></th>
            <th style="padding:7px 8px;font-size:11px;color:#9a9a93;font-weight:600;text-align:left">ETF</th>
            <th style="padding:7px 8px;font-size:11px;color:#9a9a93;font-weight:600;text-align:right">분배금</th>
            <th style="padding:7px 8px;font-size:11px;color:#9a9a93;font-weight:600;text-align:right">분배율</th>
            <th style="padding:7px 8px;font-size:11px;color:#9a9a93;font-weight:600;text-align:right">지급일</th>
          </tr>
        </thead>
        <tbody>${etfRows(list)}</tbody>
      </table>`;
  }

  // 관심 ETF 섹션
  let myEtfSection = '';
  if (myEtfs.length) {
    myEtfSection = `
      <div style="background:#edf7f1;border-radius:8px;padding:16px 20px;margin-bottom:24px">
        <div style="font-size:13px;font-weight:700;color:#1d6b38;margin-bottom:12px">
          ⭐ 내 관심 ETF 이번달 분배금
        </div>
        ${etfTable(myEtfs)}
      </div>`;
  }

  // 전체 랭킹 섹션
  const rankTitle = myEtfs.length ? '이번달 전체 랭킹' : '이번달 분배금 랭킹';
  const rankSection = otherEtfs.length ? `
    <div style="margin-bottom:20px">
      <div style="font-size:13px;font-weight:700;color:#1a1a18;margin-bottom:10px">
        📊 ${rankTitle}
      </div>
      ${etfTable(otherEtfs)}
    </div>` : '';

  return `<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f7f7f4;font-family:'Apple SD Gothic Neo',sans-serif">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td style="padding:24px 16px">
<table width="100%" style="max-width:600px;margin:0 auto;background:#fff;
  border-radius:12px;overflow:hidden;border:1px solid #e8e8e2">

  <tr><td style="background:#1d6b38;padding:20px 28px">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td style="color:#fff;font-size:17px;font-weight:700">배당픽</td>
      <td style="text-align:right;color:rgba(255,255,255,.7);font-size:12px">${month} ${timing} 공시</td>
    </tr></table>
  </td></tr>

  <tr><td style="padding:24px 28px 8px">
    <div style="font-size:18px;font-weight:700;color:#1a1a18;margin-bottom:6px">
      ${month} ${timing} 분배금액이 공시되었습니다
    </div>
    <div style="font-size:12px;color:#9a9a93;margin-bottom:24px">
      분배율 상위 15개 ETF 기준 · 최근 공시 참고 수치
    </div>

    ${myEtfSection}
    ${rankSection}
  </td></tr>

  <tr><td style="padding:8px 28px 28px;text-align:center">
    <a href="https://baedangetf.com"
       style="display:inline-block;background:#1d6b38;color:#fff;text-decoration:none;
              font-size:14px;font-weight:700;padding:13px 32px;border-radius:8px">
      전체 일정 확인하기 →
    </a>
  </td></tr>

  <tr><td style="background:#f7f7f4;padding:16px 28px;border-top:1px solid #e8e8e2;text-align:center">
    <p style="font-size:11px;color:#9a9a93;margin:0;line-height:1.8">
      본 정보는 참고 목적으로만 제공되며 투자의 최종 판단은 본인에게 있습니다.<br>
      <a href="${unsubUrl}" style="color:#9a9a93;text-decoration:underline">수신거부</a>
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body></html>`;
}


// ── 유틸 ───────────────────────────────────────────────────────
function getOrCreateSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
    sheet.appendRow(['가입일시', '이메일', '토큰', '상태', '출처', '동의여부', 'watchlist']);
    sheet.setFrozenRows(1);
  }
  return sheet;
}

function findSubscriberRow(sheet, email) {
  const rows = sheet.getDataRange().getValues();
  for (let i = 1; i < rows.length; i++) {
    if (rows[i][1] === email && rows[i][3] === '활성') return i + 1;
  }
  return null;
}

function fmtDate(s) {
  if (!s) return '-';
  const p = String(s).split('-');
  if (p.length < 3) return String(s);
  return `${parseInt(p[1])}월 ${parseInt(p[2])}일`;
}

function jsonResponse(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}


// ── 테스트 (에디터에서 직접 실행) ─────────────────────────────
function testSubscribe() {
  handleSubscribe({
    email: 'test@example.com',
    source: 'test',
    consented: true,
    watchlist: ['458730', '114800']
  });
  Logger.log('구독 테스트 완료 - 시트와 이메일 확인');
}
