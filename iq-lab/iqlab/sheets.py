"""Push the journal to Google Sheets through the Apps Script web app (apps_script/Code.gs).
Upserts by trade id, so re-sending is safe; unsynced rows are retried every cycle."""
from __future__ import annotations

import logging

import requests

from . import config, journal as J

log = logging.getLogger("iqlab")
TRADE_COLS = ["id", "created_at", "asset", "direction", "setup", "tf", "expiry_min", "entry_at", "expiry_at",
              "entry_price", "exit_price", "stake", "payout", "status", "pnl", "confidence", "rule_version",
              "regime", "iq_executed", "iq_entry_price", "iq_payout", "iq_result", "iq_pnl", "lesson", "reason"]


def sync(conn, url: str | None = None) -> dict:
    url = url or config.SHEETS_WEBHOOK
    if not url:
        return {"ok": False, "skipped": "IQLAB_SHEETS_WEBHOOK not set"}
    trades = J.rows(conn.execute("SELECT * FROM trades WHERE synced=0 ORDER BY id LIMIT 500"))
    reviews = J.rows(conn.execute("SELECT * FROM reviews WHERE synced=0"))
    payload = {
        "trades": [{c: t[c] for c in TRADE_COLS} for t in trades],
        "reviews": [{k: r[k] for k in ("date", "summary", "lessons", "proposed_changes", "stats_json")} for r in reviews],
        "watchlist": J.rows(conn.execute("SELECT * FROM watchlist ORDER BY asset")),
        "rules": J.rows(conn.execute("SELECT * FROM rule_versions ORDER BY version")),
        "risk": J.risk_status(conn),
    }
    try:
        r = requests.post(url, json=payload, timeout=30)
        ok = r.ok and r.json().get("ok")
    except Exception as e:
        log.warning("sheets sync failed: %s", e)
        return {"ok": False, "error": str(e)}
    if ok:
        conn.executemany("UPDATE trades SET synced=1 WHERE id=?", [(t["id"],) for t in trades])
        conn.executemany("UPDATE reviews SET synced=1 WHERE date=?", [(r["date"],) for r in reviews])
        conn.commit()
    return {"ok": bool(ok), "trades": len(trades), "reviews": len(reviews)}
