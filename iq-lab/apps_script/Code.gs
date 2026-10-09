/**
 * IQ Lab Journal - Google Sheets receiver.
 * 1) Extensions > Apps Script, paste this file, Save.
 * 2) Run setup() once (authorise).
 * 3) Deploy > New deployment > Web app: Execute as "Me", Access "Anyone with the link".
 * 4) Put the /exec URL in IQLAB_SHEETS_WEBHOOK on the machine that runs iq-lab.
 */
var TRADE_COLS = ['id','created_at','asset','direction','setup','tf','expiry_min','entry_at','expiry_at',
  'entry_price','exit_price','stake','payout','status','pnl','confidence','rule_version','regime',
  'iq_executed','iq_entry_price','iq_payout','iq_result','iq_pnl','lesson','reason'];
var TABS = {
  Trades: TRADE_COLS,
  Watchlist: ['asset','status','detail','updated_at'],
  Daily_Review: ['date','summary','lessons','proposed_changes','stats_json'],
  Rules: ['version','status','reason','created_at','params'],
  Stats: ['metric','value','note']
};

function setup() {
  var ss = SpreadsheetApp.getActive();
  if (!ss.getSheetByName('Trades')) ss.getSheets()[0].setName('Trades');  // reuse the first tab
  Object.keys(TABS).forEach(function (name) {
    var sh = ss.getSheetByName(name) || ss.insertSheet(name);
    sh.getRange(1, 1, 1, TABS[name].length).setValues([TABS[name]]).setFontWeight('bold');
    sh.setFrozenRows(1);
  });
  var st = ss.getSheetByName('Stats');
  var be = '(1/(1+0.85))';
  var rows = [
    ['Resolved trades (paper)', '=COUNTIF(Trades!N:N,"WIN")+COUNTIF(Trades!N:N,"LOSS")', 'ties excluded'],
    ['Wins', '=COUNTIF(Trades!N:N,"WIN")', ''],
    ['Win rate (paper)', '=IFERROR(B3/B2,"")', ''],
    ['Breakeven win rate', '=' + be, 'payout 85%'],
    ['Lower 95% (Wilson, one-sided)', '=IFERROR((B3/B2+1.645^2/(2*B2)-1.645*SQRT(B3/B2*(1-B3/B2)/B2+1.645^2/(4*B2^2)))/(1+1.645^2/B2),"")', 'must be > breakeven'],
    ['P&L paper (USD)', '=SUM(Trades!O:O)', ''],
    ['IQ demo trades', '=COUNTIF(Trades!V:V,"WIN")+COUNTIF(Trades!V:V,"LOSS")', ''],
    ['Win rate (IQ demo)', '=IFERROR(COUNTIF(Trades!V:V,"WIN")/B8,"")', ''],
    ['P&L IQ demo (USD)', '=SUM(Trades!W:W)', ''],
    ['Gate: >=500 trades & >=58% & lower95 > breakeven', '=IF(AND(B2>=500,B4>=0.58,B6>B5),"PASSED","NOT YET")', 'real money only after PASSED']
  ];
  st.getRange(2, 1, rows.length, 3).setValues(rows);
  st.getRange('B4:B6').setNumberFormat('0.0%');
  st.getRange('B9').setNumberFormat('0.0%');
}

function doPost(e) {
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var p = JSON.parse(e.postData.contents);
    var ss = SpreadsheetApp.getActive();
    upsert_(ss.getSheetByName('Trades'), TRADE_COLS, p.trades || [], 'id');
    upsert_(ss.getSheetByName('Daily_Review'), TABS.Daily_Review, p.reviews || [], 'date');
    replace_(ss.getSheetByName('Watchlist'), TABS.Watchlist, p.watchlist || []);
    replace_(ss.getSheetByName('Rules'), TABS.Rules, p.rules || []);
    return json_({ok: true, trades: (p.trades || []).length});
  } catch (err) {
    return json_({ok: false, error: String(err)});
  } finally {
    lock.releaseLock();
  }
}

function doGet() {
  return json_({ok: true, service: 'iq-lab journal'});
}

function upsert_(sh, cols, items, key) {
  if (!items.length) return;
  var last = sh.getLastRow();
  var keyCol = cols.indexOf(key);
  var keys = last > 1 ? sh.getRange(2, keyCol + 1, last - 1, 1).getValues().map(function (r) { return String(r[0]); }) : [];
  items.forEach(function (it) {
    var row = cols.map(function (c) { return it[c] === null || it[c] === undefined ? '' : it[c]; });
    var i = keys.indexOf(String(it[key]));
    if (i >= 0) {
      sh.getRange(i + 2, 1, 1, cols.length).setValues([row]);
    } else {
      sh.appendRow(row);
      keys.push(String(it[key]));
    }
  });
}

function replace_(sh, cols, items) {
  var last = sh.getLastRow();
  if (last > 1) sh.getRange(2, 1, last - 1, cols.length).clearContent();
  if (!items.length) return;
  sh.getRange(2, 1, items.length, cols.length).setValues(items.map(function (it) {
    return cols.map(function (c) { return it[c] === null || it[c] === undefined ? '' : it[c]; });
  }));
}

function json_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}
