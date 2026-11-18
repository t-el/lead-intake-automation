// Deploy as: Extensions > Apps Script > Deploy > New deployment > Web app (execute as you, anyone with link).
// Upserts one row per email into the first sheet.
function doPost(e) {
  const row = JSON.parse(e.postData.contents);
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  const headers = Object.keys(row);
  if (sheet.getLastRow() === 0) sheet.appendRow(headers);
  const current = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const emailCol = current.indexOf('email') + 1;
  const values = current.map((h) => row[h] ?? '');
  const emails = sheet.getLastRow() > 1 ? sheet.getRange(2, emailCol, sheet.getLastRow() - 1, 1).getValues().flat() : [];
  const idx = emails.indexOf(row.email);
  if (idx >= 0) sheet.getRange(idx + 2, 1, 1, values.length).setValues([values]);
  else sheet.appendRow(values);
  return ContentService.createTextOutput(JSON.stringify({ ok: true })).setMimeType(ContentService.MimeType.JSON);
}
