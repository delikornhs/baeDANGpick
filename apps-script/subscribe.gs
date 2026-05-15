// ================================================================
// 배당픽 이메일 구독 - Google Apps Script
//
// [배포 방법]
// 1. Google Sheets 새 시트 만들기 (헤더: 타임스탬프 | 이메일 | 출처 | 동의여부)
// 2. 확장 프로그램 → Apps Script 열기
// 3. 이 코드 붙여넣기
// 4. STIBEE_API_KEY, STIBEE_LIST_ID 값 입력
// 5. 배포 → 새 배포 → 웹앱 → 액세스: 모든 사용자 → 배포
// 6. 생성된 웹앱 URL을 index.html의 SUBSCRIBE_URL에 붙여넣기
// ================================================================

const STIBEE_API_KEY = 'YOUR_STIBEE_API_KEY';   // 스티비 API 키
const STIBEE_LIST_ID = 'YOUR_STIBEE_LIST_ID';   // 스티비 구독자 리스트 ID
const SHEET_NAME     = '구독자';                  // 시트 이름 (없으면 첫 번째 시트 사용)

function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);
    const email     = (data.email     || '').trim().toLowerCase();
    const source    = data.source     || 'unknown';
    const consented = data.consented  || false;

    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      return jsonResponse({result: 'error', message: '이메일 형식 오류'});
    }

    // 1) Google Sheets 저장
    saveToSheet(email, source, consented);

    // 2) 스티비 구독자 추가
    addToStibee(email);

    return jsonResponse({result: 'success'});
  } catch (err) {
    return jsonResponse({result: 'error', message: err.message});
  }
}

function saveToSheet(email, source, consented) {
  const ss     = SpreadsheetApp.getActiveSpreadsheet();
  let   sheet  = ss.getSheetByName(SHEET_NAME);
  if (!sheet) sheet = ss.getSheets()[0];

  // 첫 행이 비어있으면 헤더 추가
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(['타임스탬프', '이메일', '출처', '동의여부']);
  }
  sheet.appendRow([new Date(), email, source, consented ? '동의' : '미동의']);
}

function addToStibee(email) {
  if (!STIBEE_API_KEY || STIBEE_API_KEY === 'YOUR_STIBEE_API_KEY') return;

  const url     = `https://api.stibee.com/v1/lists/${STIBEE_LIST_ID}/subscribers`;
  const payload = JSON.stringify({
    subscribers: [{email}],
    groupIds: []
  });

  UrlFetchApp.fetch(url, {
    method:  'POST',
    headers: {
      'AccessToken':   STIBEE_API_KEY,
      'Content-Type':  'application/json'
    },
    payload: payload,
    muteHttpExceptions: true
  });
}

function jsonResponse(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

// ================================================================
// [테스트용] Apps Script 에디터에서 직접 실행해 동작 확인
function testSave() {
  saveToSheet('test@example.com', 'manual-test', true);
  Logger.log('저장 완료');
}
// ================================================================
