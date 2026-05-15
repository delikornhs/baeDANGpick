// ================================================================
// 배당픽 이메일 구독 - Google Apps Script (Gmail 직접 발송)
//
// [Script Properties 설정 필요] Apps Script → 프로젝트 설정 → 스크립트 속성
//   NEWSLETTER_SECRET : GitHub Actions 트리거용 비밀키 (예: baeDANGpick2026!)
//
// [배포] 기존 배포 URL 유지 → 배포 관리 → 연필 아이콘 → 버전 새버전으로 교체
// ================================================================

const SHEET_NAME  = '구독자';
const SENDER_NAME = '배당픽';

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
  const email = (data.email || '').trim().toLowerCase();
  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return jsonResponse({ result: 'error', message: '이메일 형식 오류' });
  }

  const sheet = getOrCreateSheet();

  // 중복 확인
  if (findSubscriberRow(sheet, email)) {
    return jsonResponse({ result: 'already', message: '이미 등록된 이메일입니다.' });
  }

  const token     = Utilities.getUuid();
  const scriptUrl = ScriptApp.getService().getUrl();

  sheet.appendRow([
    new Date(),
    email,
    token,
    '활성',
    data.source    || 'web',
    data.consented ? '동의' : '미동의'
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
          <p style="color:#555">배당픽 이메일 수신이 해지되었습니다.</p>
          <a href="https://bae-dang-pick.vercel.app"
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
  const secret = PropertiesService.getScriptProperties().getProperty('NEWSLETTER_SECRET');
  if (!secret || data.secret !== secret) {
    return jsonResponse({ result: 'error', message: 'unauthorized' });
  }

  const sheet     = getOrCreateSheet();
  const rows      = sheet.getDataRange().getValues();
  const scriptUrl = ScriptApp.getService().getUrl();
  const etfs      = data.etfs  || [];
  const month     = data.month || '';
  const subject   = `[배당픽] ${month} ETF 분배금 일정 업데이트`;

  let sent = 0, failed = 0;

  for (let i = 1; i < rows.length; i++) {
    const email  = rows[i][1];
    const token  = rows[i][2];
    const status = rows[i][3];
    if (status !== '활성') continue;

    try {
      const html = buildNewsletterHtml(etfs, month, scriptUrl, token);
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
    subject:  '[배당픽] 이메일 알림 신청이 완료되었습니다',
    name:     SENDER_NAME,
    htmlBody: `
    <div style="font-family:sans-serif;max-width:520px;margin:0 auto;padding:20px">
      <div style="background:#1d6b38;border-radius:10px 10px 0 0;padding:20px 24px">
        <span style="color:#fff;font-size:17px;font-weight:700">₩ 배당픽</span>
      </div>
      <div style="border:1px solid #e8e8e2;border-top:none;border-radius:0 0 10px 10px;padding:28px 24px">
        <h2 style="color:#1d6b38;margin:0 0 12px">알림 신청 완료!</h2>
        <p style="color:#444;line-height:1.7;margin:0 0 20px">
          매월 ETF 분배금 일정(배당락일·지급일·분배금액)이 업데이트될 때<br>이메일로 안내해 드리겠습니다.
        </p>
        <a href="https://bae-dang-pick.vercel.app"
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

// ── 뉴스레터 HTML 빌더 ─────────────────────────────────────────
function buildNewsletterHtml(etfs, month, scriptUrl, token) {
  const unsubUrl = `${scriptUrl}?action=unsubscribe&token=${token}`;

  const rows = etfs.slice(0, 15).map(e => `
    <tr>
      <td style="padding:9px 12px;border-bottom:1px solid #f0f0f0;font-size:12px;color:#1a1a18">
        [${e.brand}] ${e.name}
      </td>
      <td style="padding:9px 12px;border-bottom:1px solid #f0f0f0;font-size:12px;
                 text-align:center;color:#4a4a45;font-family:monospace">${e.ex}</td>
      <td style="padding:9px 12px;border-bottom:1px solid #f0f0f0;font-size:12px;
                 text-align:center;color:#4a4a45;font-family:monospace">${e.pay}</td>
      <td style="padding:9px 12px;border-bottom:1px solid #f0f0f0;font-size:13px;
                 text-align:right;color:#1d6b38;font-weight:700">
        ${Number(e.dist).toLocaleString()}원
      </td>
      <td style="padding:9px 12px;border-bottom:1px solid #f0f0f0;font-size:13px;
                 text-align:right;color:#1d6b38;font-weight:700">${e.rate}%</td>
    </tr>`).join('');

  return `<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f7f7f4;font-family:'Apple SD Gothic Neo',sans-serif">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td style="padding:24px 16px">
<table width="100%" style="max-width:600px;margin:0 auto;background:#fff;
       border-radius:12px;overflow:hidden;border:1px solid #e8e8e2">

  <!-- 헤더 -->
  <tr><td style="background:#1d6b38;padding:20px 28px">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td style="color:#fff;font-size:17px;font-weight:700">₩ 배당픽</td>
      <td style="text-align:right;color:rgba(255,255,255,.7);font-size:12px">${month} 업데이트</td>
    </tr></table>
  </td></tr>

  <!-- 제목 -->
  <tr><td style="padding:24px 28px 16px">
    <div style="font-size:18px;font-weight:700;color:#1a1a18;margin-bottom:6px">
      ${month} ETF 분배금 일정이 업데이트되었습니다
    </div>
    <div style="font-size:12px;color:#9a9a93">분배율 상위 15개 ETF 기준 · 최근 공시 참고 수치</div>
  </td></tr>

  <!-- 테이블 -->
  <tr><td style="padding:0 28px 20px">
    <table width="100%" cellpadding="0" cellspacing="0"
           style="border:1px solid #e8e8e2;border-radius:8px;overflow:hidden;border-collapse:collapse">
      <tr style="background:#edf7f1">
        <th style="padding:9px 12px;font-size:11px;color:#1d6b38;text-align:left;font-weight:700">ETF</th>
        <th style="padding:9px 12px;font-size:11px;color:#1d6b38;text-align:center;font-weight:700">배당락일</th>
        <th style="padding:9px 12px;font-size:11px;color:#1d6b38;text-align:center;font-weight:700">지급일</th>
        <th style="padding:9px 12px;font-size:11px;color:#1d6b38;text-align:right;font-weight:700">주당분배금</th>
        <th style="padding:9px 12px;font-size:11px;color:#1d6b38;text-align:right;font-weight:700">분배율</th>
      </tr>
      ${rows}
    </table>
  </td></tr>

  <!-- CTA -->
  <tr><td style="padding:4px 28px 28px;text-align:center">
    <a href="https://bae-dang-pick.vercel.app"
       style="display:inline-block;background:#1d6b38;color:#fff;text-decoration:none;
              font-size:14px;font-weight:700;padding:13px 32px;border-radius:8px">
      전체 일정 확인하기 →
    </a>
  </td></tr>

  <!-- 푸터 -->
  <tr><td style="background:#f7f7f4;padding:16px 28px;border-top:1px solid #e8e8e2;text-align:center">
    <p style="font-size:11px;color:#9a9a93;margin:0;line-height:1.8">
      본 정보는 참고 목적으로만 제공되며 투자의 최종 판단은 본인에게 있습니다.<br>
      <a href="${unsubUrl}" style="color:#9a9a93;text-decoration:underline">수신거부</a>
    </p>
  </td></tr>

</table>
</td></tr></table>
</body></html>`;
}

// ── 유틸 ───────────────────────────────────────────────────────
function getOrCreateSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
    sheet.appendRow(['가입일시', '이메일', '토큰', '상태', '출처', '동의여부']);
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

function jsonResponse(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

// ── 테스트 (에디터에서 직접 실행) ─────────────────────────────
function testSubscribe() {
  handleSubscribe({ email: 'test@example.com', source: 'test', consented: true });
  Logger.log('구독 테스트 완료 - 시트와 이메일 확인');
}
