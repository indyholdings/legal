"""MCP server `iq-lab`: the tools Claude uses to run the IQ Option demo research loop."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from . import config, engine, journal as J, sheets

INSTRUCTIONS = """IQ Lab - research harness for IQ Option PRACTICE (demo) trading.
Loop: scan_market -> get_executable_signals -> place each ticket on IQ Option in Chrome
(PRACTICE balance only) -> confirm_iq_execution -> after expiry record_iq_result.
Never trade a REAL balance. Rule changes are proposals; only the human approves them."""

mcp = _Server("iq-lab", instructions=INSTRUCTIONS)
_conn = None


def conn():
    global _conn
    if _conn is None:
        _conn = J.connect()
    return _conn


def _ticket(t: dict) -> dict:
    return {
        "trade_id": t["id"], "asset": t["asset"], "direction": t["direction"],
        "iq_button": "HIGHER (green, up)" if t["direction"] == "CALL" else "LOWER (red, down)",
        "expiry_min": t["expiry_min"], "stake": t["stake"], "setup": t["setup"],
        "confidence": t["confidence"], "signal_price": t["entry_price"], "reason": t["reason"],
        "age_sec": int((J.utcnow() - J.parse(t["created_at"])).total_seconds()),
    }


@mcp.tool()
def scan_market() -> dict:
    """Run one cycle: resolve expired trades, scan all assets, journal new signals.
    Returns new signals, the watchlist (what is being watched and why) and risk status."""
    out = engine.run_cycle(conn())
    out["new_trades"] = [_ticket(t) for t in out["new_trades"]]
    out["sheets"] = sheets.sync(conn())
    return out


@mcp.tool()
def get_executable_signals() -> list[dict]:
    """Fresh signals not yet placed on IQ Option (younger than the max signal age).
    Each ticket says which IQ button to press, the expiry and the stake."""
    cutoff = J.iso(J.utcnow() - timedelta(seconds=config.SIGNAL_MAX_AGE_SEC))
    rows = J.rows(conn().execute(
        "SELECT * FROM trades WHERE status='OPEN' AND iq_executed=0 AND created_at >= ? ORDER BY confidence DESC", (cutoff,)))
    return [_ticket(t) for t in rows]


@mcp.tool()
def confirm_iq_execution(trade_id: int, iq_entry_price: float | None = None, iq_payout_pct: float | None = None) -> str:
    """Call right after the trade is placed on the IQ PRACTICE account.
    iq_payout_pct is the payout IQ showed, e.g. 87 for 87%."""
    J.confirm_iq_execution(conn(), trade_id, iq_entry_price, iq_payout_pct / 100 if iq_payout_pct else None)
    return f"trade {trade_id} marked as executed on IQ demo"


@mcp.tool()
def record_iq_result(trade_id: int, result: str, iq_pnl: float | None = None) -> str:
    """Record what IQ Option showed when the option expired: WIN, LOSS or TIE (+ optional P&L)."""
    J.record_iq_result(conn(), trade_id, result, iq_pnl)
    sheets.sync(conn())
    return f"trade {trade_id}: IQ result {result.upper()} recorded"


@mcp.tool()
def get_trades(date_th: str | None = None, status: str | None = None, limit: int = 50) -> list[dict]:
    """Journal rows. date_th='YYYY-MM-DD' (Thai date), status OPEN/WIN/LOSS/TIE/VOID."""
    rows = J.rows(conn().execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (max(limit, 1) * 10,)))
    if date_th:
        rows = [r for r in rows if J.th_date(J.parse(r["entry_at"])) == date_th]
    if status:
        rows = [r for r in rows if r["status"] == status.upper()]
    return rows[:limit]


@mcp.tool()
def get_stats(scope: str = "paper", days: int | None = None) -> dict:
    """Win rate overall and by setup/asset/hour/regime with 95% lower bound vs breakeven,
    plus progress toward the real-money gate. scope: 'paper' (all signals) or 'iq' (IQ demo results)."""
    since = J.iso(J.utcnow() - timedelta(days=days)) if days else None
    s = J.stats(conn(), scope, since)
    s["equity"] = s["equity"][-50:]
    return s


@mcp.tool()
def get_risk_status() -> dict:
    """Today's trade count, P&L, losing streak and whether trading is blocked."""
    return J.risk_status(conn())


@mcp.tool()
def daily_review_data(date_th: str | None = None) -> dict:
    """Everything needed for the end-of-day review: the day's trades (losses first), stats,
    cumulative stats per setup and the active rules."""
    date_th = date_th or J.th_date(J.utcnow())
    day = [r for r in J.rows(conn().execute("SELECT * FROM trades ORDER BY entry_at"))
           if J.th_date(J.parse(r["entry_at"])) == date_th]
    res = [r["status"] for r in day]
    version, rules = J.active_rules(conn())
    return {
        "date_th": date_th, "day_summary": J._summary(res), "day_pnl": round(sum(r["pnl"] or 0 for r in day), 2),
        "losses": [r for r in day if r["status"] == "LOSS"], "wins": [r for r in day if r["status"] == "WIN"],
        "iq_vs_paper_mismatch": [r["id"] for r in day if r["iq_result"] and r["iq_result"] != r["status"]],
        "cumulative": {k: v for k, v in J.stats(conn()).items() if k in ("n", "winrate", "wr_lower95", "by_setup", "gate")},
        "rule_version": version, "rules": rules,
        "review_rules": "Propose a change only for a setup with >= 50 trades, one parameter at a time.",
    }


@mcp.tool()
def save_daily_review(summary: str, lessons: str, proposed_changes: str = "", date_th: str | None = None) -> str:
    """Store the daily review (also synced to the Daily_Review tab in Google Sheets)."""
    date_th = date_th or J.th_date(J.utcnow())
    st = J.stats(conn())
    conn().execute("INSERT OR REPLACE INTO reviews VALUES (?, ?, ?, ?, ?, ?, 0)",
                   (date_th, summary, lessons, proposed_changes,
                    json.dumps({k: st[k] for k in ("n", "winrate", "wr_lower95", "pnl")}), J.iso(J.utcnow())))
    conn().commit()
    sheets.sync(conn())
    return f"review for {date_th} saved"


@mcp.tool()
def add_lesson(trade_id: int, lesson: str) -> str:
    """Attach a one-line lesson to a trade (why it won or lost)."""
    J.add_lesson(conn(), trade_id, lesson)
    return "saved"


@mcp.tool()
def add_news_blackout(start_th: str, label: str, minutes_before: int = 30, minutes_after: int = 30) -> str:
    """Block new signals around a high-impact news event. start_th='YYYY-MM-DD HH:MM' Thai time."""
    t = datetime.strptime(start_th, "%Y-%m-%d %H:%M").replace(tzinfo=J.TH)
    conn().execute("INSERT INTO blackouts (start_utc, end_utc, label) VALUES (?, ?, ?)",
                   (J.iso(t - timedelta(minutes=minutes_before)), J.iso(t + timedelta(minutes=minutes_after)), label))
    conn().commit()
    return f"blackout '{label}' set around {start_th} (TH)"


@mcp.tool()
def get_rules() -> dict:
    """Active rule version and parameters, plus pending proposals."""
    version, rules = J.active_rules(conn())
    pending = J.rows(conn().execute("SELECT version, reason, created_at FROM rule_versions WHERE status='PROPOSED'"))
    return {"active_version": version, "rules": rules, "pending_proposals": pending}


@mcp.tool()
def propose_rule_change(setup: str, param: str, value: float | int | bool, reason: str) -> str:
    """Propose changing ONE parameter of one setup. It stays PROPOSED until the human runs
    `python -m iqlab rules approve <version>`."""
    v = J.propose_rules(conn(), {setup: {param: value}}, reason)
    return f"proposal v{v} created; ask the human to approve: python -m iqlab rules approve {v}"


@mcp.tool()
def sync_sheets() -> dict:
    """Push unsynced journal rows, reviews and the watchlist to Google Sheets."""
    return sheets.sync(conn())


def main():
    mcp.run()


if __name__ == "__main__":
    main()
