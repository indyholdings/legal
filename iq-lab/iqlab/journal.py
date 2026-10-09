"""SQLite trading journal: trades, watchlist, daily reviews, versioned rules, stats."""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import config
from .rules import DEFAULT_RULES

TH = ZoneInfo(config.TZ)

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  signal_key TEXT UNIQUE,
  created_at TEXT, asset TEXT, symbol TEXT, direction TEXT, setup TEXT, tf TEXT,
  expiry_min INTEGER, entry_at TEXT, expiry_at TEXT,
  entry_price REAL, exit_price REAL, stake REAL, payout REAL,
  status TEXT DEFAULT 'OPEN', pnl REAL, confidence REAL, rule_version INTEGER,
  regime TEXT, reason TEXT,
  iq_executed INTEGER DEFAULT 0, iq_executed_at TEXT, iq_entry_price REAL, iq_payout REAL,
  iq_result TEXT, iq_pnl REAL,
  lesson TEXT, synced INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS watchlist (asset TEXT PRIMARY KEY, status TEXT, detail TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS reviews (
  date TEXT PRIMARY KEY, summary TEXT, lessons TEXT, proposed_changes TEXT, stats_json TEXT,
  created_at TEXT, synced INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS rule_versions (
  version INTEGER PRIMARY KEY, params TEXT, status TEXT, reason TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS blackouts (id INTEGER PRIMARY KEY AUTOINCREMENT, start_utc TEXT, end_utc TEXT, label TEXT);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse(s: str) -> datetime:
    return datetime.fromisoformat(s)


def th_date(dt: datetime) -> str:
    return dt.astimezone(TH).date().isoformat()


def connect(path=None) -> sqlite3.Connection:
    path = path or config.DB_PATH
    if str(path) != ":memory:":
        config.Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    if not conn.execute("SELECT 1 FROM rule_versions").fetchone():
        conn.execute(
            "INSERT INTO rule_versions VALUES (1, ?, 'ACTIVE', 'baseline', ?)",
            (json.dumps(DEFAULT_RULES), iso(utcnow())),
        )
    conn.commit()
    return conn


# ---------- rules ----------
def active_rules(conn) -> tuple[int, dict]:
    r = conn.execute("SELECT version, params FROM rule_versions WHERE status='ACTIVE' ORDER BY version DESC").fetchone()
    return r["version"], json.loads(r["params"])


def propose_rules(conn, changes: dict, reason: str) -> int:
    """changes = {"S2_mean_reversion": {"adx_max": 18}} merged onto the active params."""
    _, params = active_rules(conn)
    for setup, kv in changes.items():
        if setup not in params:
            raise ValueError(f"unknown setup {setup}")
        unknown = set(kv) - set(params[setup])
        if unknown:
            raise ValueError(f"unknown params for {setup}: {sorted(unknown)}")
        params[setup].update(kv)
    v = conn.execute("SELECT MAX(version) FROM rule_versions").fetchone()[0] + 1
    conn.execute("INSERT INTO rule_versions VALUES (?, ?, 'PROPOSED', ?, ?)", (v, json.dumps(params), reason, iso(utcnow())))
    conn.commit()
    return v


def set_rule_status(conn, version: int, approve: bool) -> None:
    r = conn.execute("SELECT status FROM rule_versions WHERE version=?", (version,)).fetchone()
    if not r or r["status"] != "PROPOSED":
        raise ValueError(f"version {version} is not a pending proposal")
    if approve:
        conn.execute("UPDATE rule_versions SET status='RETIRED' WHERE status='ACTIVE'")
        conn.execute("UPDATE rule_versions SET status='ACTIVE' WHERE version=?", (version,))
    else:
        conn.execute("UPDATE rule_versions SET status='REJECTED' WHERE version=?", (version,))
    conn.commit()


# ---------- trades ----------
def open_trade(conn, t: dict) -> int | None:
    cols = ["signal_key", "created_at", "asset", "symbol", "direction", "setup", "tf", "expiry_min", "entry_at",
            "expiry_at", "entry_price", "stake", "payout", "confidence", "rule_version", "regime", "reason"]
    try:
        cur = conn.execute(
            f"INSERT INTO trades ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [t[c] for c in cols]
        )
    except sqlite3.IntegrityError:
        return None  # signal already journaled
    conn.commit()
    return cur.lastrowid


def outcome(direction: str, entry: float, exit_: float) -> str:
    if exit_ == entry:
        return "TIE"
    return "WIN" if (exit_ > entry) == (direction == "CALL") else "LOSS"


def pnl_for(result: str, stake: float, payout: float) -> float:
    return round(stake * payout, 2) if result == "WIN" else (-stake if result == "LOSS" else 0.0)


def resolve_trade(conn, trade_id: int, exit_price: float | None, void: bool = False) -> str:
    t = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
    if void:
        res, pnl = "VOID", 0.0
    else:
        res = outcome(t["direction"], t["entry_price"], exit_price)
        pnl = pnl_for(res, t["stake"], t["payout"])
    conn.execute("UPDATE trades SET exit_price=?, status=?, pnl=?, synced=0 WHERE id=?", (exit_price, res, pnl, trade_id))
    conn.commit()
    return res


def confirm_iq_execution(conn, trade_id: int, iq_entry_price: float | None, iq_payout: float | None) -> None:
    conn.execute(
        "UPDATE trades SET iq_executed=1, iq_executed_at=?, iq_entry_price=?, iq_payout=?, synced=0 WHERE id=?",
        (iso(utcnow()), iq_entry_price, iq_payout, trade_id),
    )
    conn.commit()


def record_iq_result(conn, trade_id: int, result: str, iq_pnl: float | None = None) -> None:
    result = result.upper()
    if result not in ("WIN", "LOSS", "TIE"):
        raise ValueError("result must be WIN, LOSS or TIE")
    t = conn.execute("SELECT stake, payout, iq_payout FROM trades WHERE id=?", (trade_id,)).fetchone()
    if iq_pnl is None:
        iq_pnl = pnl_for(result, t["stake"], t["iq_payout"] or t["payout"])
    conn.execute("UPDATE trades SET iq_result=?, iq_pnl=?, iq_executed=1, synced=0 WHERE id=?", (result, iq_pnl, trade_id))
    conn.commit()


def add_lesson(conn, trade_id: int, lesson: str) -> None:
    conn.execute("UPDATE trades SET lesson=?, synced=0 WHERE id=?", (lesson, trade_id))
    conn.commit()


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


# ---------- stats ----------
def wilson_lower(wins: int, n: int, z: float = 1.645) -> float:
    """One-sided 95% lower bound of the true win rate."""
    if n == 0:
        return 0.0
    p = wins / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / denom


def _summary(results: list[str]) -> dict:
    w = results.count("WIN")
    l = results.count("LOSS")
    n = w + l
    return {"n": n, "wins": w, "losses": l, "ties": results.count("TIE"),
            "winrate": round(w / n, 4) if n else None, "wr_lower95": round(wilson_lower(w, n), 4)}


def stats(conn, scope: str = "paper", since: str | None = None) -> dict:
    """scope='paper': feed-resolved results of every signal. scope='iq': results recorded on IQ demo."""
    res_col, pnl_col = ("status", "pnl") if scope == "paper" else ("iq_result", "iq_pnl")
    q = f"SELECT *, {res_col} AS r, {pnl_col} AS p FROM trades WHERE {res_col} IN ('WIN','LOSS','TIE')"
    args = []
    if since:
        q += " AND expiry_at >= ?"
        args.append(since)
    trades = rows(conn.execute(q + " ORDER BY expiry_at", args))
    be = config.breakeven_winrate()
    out = _summary([t["r"] for t in trades])
    out.update({"scope": scope, "breakeven": round(be, 4), "pnl": round(sum(t["p"] or 0 for t in trades), 2)})
    groups = {}
    for key, fn in (("by_setup", lambda t: t["setup"]), ("by_asset", lambda t: t["asset"]),
                    ("by_hour_th", lambda t: f"{parse(t['entry_at']).astimezone(TH).hour:02d}"),
                    ("by_direction", lambda t: t["direction"]), ("by_regime", lambda t: t["regime"] or "?")):
        g = {}
        for t in trades:
            g.setdefault(fn(t), []).append(t["r"])
        groups[key] = {k: _summary(v) for k, v in sorted(g.items())}
    out.update(groups)
    eq, run = [], 0.0
    for t in trades:
        run += t["p"] or 0
        eq.append([t["expiry_at"], round(run, 2)])
    out["equity"] = eq
    out["gate"] = gate(out["n"], out["wins"], be)
    return out


def gate(n: int, wins: int, be: float) -> dict:
    wr = wins / n if n else 0.0
    lb = wilson_lower(wins, n)
    passed = n >= config.GATE_MIN_TRADES and wr >= config.GATE_MIN_WINRATE and lb > be
    return {"passed": passed, "progress_trades": f"{n}/{config.GATE_MIN_TRADES}",
            "need": f">= {config.GATE_MIN_TRADES} trades, winrate >= {config.GATE_MIN_WINRATE:.0%}, "
                    f"lower95 > breakeven {be:.1%}"}


def risk_status(conn, now: datetime | None = None) -> dict:
    now = now or utcnow()
    today = th_date(now)
    todays = [t for t in rows(conn.execute("SELECT * FROM trades ORDER BY entry_at")) if th_date(parse(t["entry_at"])) == today]
    resolved = [t for t in todays if t["status"] in ("WIN", "LOSS", "TIE")]
    consec = 0
    for t in reversed(resolved):
        if t["status"] == "LOSS":
            consec += 1
        elif t["status"] == "WIN":
            break
    pnl = round(sum(t["pnl"] or 0 for t in resolved), 2)
    bal = config.DEMO_BALANCE
    blocked = None
    if len(todays) >= config.MAX_TRADES_PER_DAY:
        blocked = f"max {config.MAX_TRADES_PER_DAY} trades/day reached"
    elif consec >= config.MAX_CONSEC_LOSSES:
        blocked = f"{consec} losses in a row - stop for today"
    elif pnl <= -config.DAILY_LOSS_LIMIT_PCT * bal:
        blocked = f"daily loss limit {config.DAILY_LOSS_LIMIT_PCT:.0%} hit"
    elif pnl >= config.DAILY_PROFIT_LOCK_PCT * bal:
        blocked = f"daily profit lock {config.DAILY_PROFIT_LOCK_PCT:.0%} hit"
    if not config.ENFORCE_DAILY_STOPS and blocked and "max" not in blocked:
        blocked = None
    return {"date_th": today, "trades_today": len(todays), "open": sum(t["status"] == "OPEN" for t in todays),
            "consec_losses": consec, "pnl_today": pnl, "pnl_today_pct": round(pnl / bal, 4),
            "blocked": blocked, "stake": round(config.STAKE_PCT * bal, 2)}


def in_blackout(conn, now: datetime) -> str | None:
    r = conn.execute("SELECT label FROM blackouts WHERE start_utc <= ? AND end_utc >= ?", (iso(now), iso(now))).fetchone()
    return r["label"] if r else None


def set_meta(conn, key: str, value) -> None:
    conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, json.dumps(value)))
    conn.commit()


def get_meta(conn, key: str, default=None):
    r = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default
