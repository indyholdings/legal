"""One scan cycle: resolve expired trades, scan every asset, journal new signals.

Every signal that passes the filters is journaled as a paper trade (resolved from the
price feed). Claude then mirrors fresh signals on the IQ Option Practice account and
records the real IQ result on the same row, so paper and IQ stats can be compared.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd

from . import config, journal as J
from .data import INTERVAL_SEC, YahooProvider
from .strategies import STRATEGIES, market_context

log = logging.getLogger("iqlab")
RESOLVE_GRACE = timedelta(seconds=75)   # wait for the exit bar to close and reach the feed
VOID_AFTER = timedelta(minutes=30)      # give up if the feed never delivers the exit bar


def in_session(now: datetime) -> bool:
    h = now.astimezone(J.TH).hour
    start, end = config.SESSION_HOURS
    return start <= h < end if start < end else (h >= start or h < end)


def resolve_due(conn, provider, now: datetime) -> list[dict]:
    done = []
    due = J.rows(conn.execute("SELECT * FROM trades WHERE status='OPEN' AND expiry_at <= ?", (J.iso(now - RESOLVE_GRACE),)))
    cache: dict[str, pd.DataFrame] = {}
    for t in due:
        exit_bar = pd.Timestamp(J.parse(t["expiry_at"])) - pd.Timedelta(minutes=1)
        try:
            if t["symbol"] not in cache:
                cache[t["symbol"]] = provider.candles(t["symbol"], "1m", pd.Timestamp(now))
            df = cache[t["symbol"]]
            if exit_bar in df.index:
                res = J.resolve_trade(conn, t["id"], float(df.loc[exit_bar, "close"]))
                done.append({"id": t["id"], "asset": t["asset"], "result": res})
                continue
        except Exception as e:  # feed hiccup: retry next cycle
            log.warning("resolve %s failed: %s", t["id"], e)
        if now - J.parse(t["expiry_at"]) > VOID_AFTER:
            J.resolve_trade(conn, t["id"], None, void=True)
            done.append({"id": t["id"], "asset": t["asset"], "result": "VOID"})
    return done


def scan(conn, provider, now: datetime, journal_signals: bool = True) -> dict:
    version, rules = J.active_rules(conn)
    risk = J.risk_status(conn, now)
    session = in_session(now)
    blackout = J.in_blackout(conn, now)
    open_assets = {r["asset"] for r in conn.execute("SELECT asset FROM trades WHERE status='OPEN'")}
    new_trades, watch = [], []
    ts_now = pd.Timestamp(now)

    for asset, symbol in config.ASSETS.items():
        frames, status, notes = {}, "SCANNING", []
        try:
            for tf in {p["tf"] for p in rules.values() if p.get("enabled")} | {"5m"}:
                frames[tf] = provider.candles(symbol, tf, ts_now)
        except Exception as e:
            watch.append({"asset": asset, "status": "NO DATA", "detail": str(e)[:120]})
            continue
        ctx = market_context(frames["5m"])
        notes.append(ctx["text"])

        for setup, p in rules.items():
            if not p.get("enabled"):
                continue
            df = frames[p["tf"]]
            if len(df) < 60:
                continue
            sig = STRATEGIES[setup](df, p).iloc[-1]
            if not sig["direction"]:
                continue
            bar_open = df.index[-1]
            entry_at = bar_open + pd.Timedelta(seconds=INTERVAL_SEC[p["tf"]])
            if ts_now - entry_at > pd.Timedelta(seconds=config.SIGNAL_MAX_AGE_SEC + INTERVAL_SEC[p["tf"]]):
                continue  # stale bar (feed lag / market closed)
            label = f"{setup.split('_')[0]} {sig['direction']}"
            skip = None
            if not session:
                skip = "out of session"
            elif blackout:
                skip = f"news blackout: {blackout}"
            elif risk["blocked"]:
                skip = risk["blocked"]
            elif asset in open_assets:
                skip = "trade already open on asset"
            if skip:
                notes.append(f"{label} skipped ({skip})")
                continue
            status = "SIGNAL"
            notes.append(f"{label} FIRED")
            if not journal_signals:
                continue
            t = {
                "signal_key": f"{asset}|{setup}|{bar_open.isoformat()}",
                "created_at": J.iso(now), "asset": asset, "symbol": symbol,
                "direction": sig["direction"], "setup": setup, "tf": p["tf"], "expiry_min": p["expiry_min"],
                "entry_at": J.iso(entry_at.to_pydatetime()),
                "expiry_at": J.iso((entry_at + pd.Timedelta(minutes=p["expiry_min"])).to_pydatetime()),
                "entry_price": float(df["close"].iloc[-1]), "stake": risk["stake"], "payout": config.DEFAULT_PAYOUT,
                "confidence": float(sig["confidence"]), "rule_version": version, "regime": ctx["regime"],
                "reason": f"{setup} {sig['direction']} on {p['tf']} close {df['close'].iloc[-1]:.5f} | {ctx['text']}",
            }
            tid = J.open_trade(conn, t)
            if tid:
                t["id"] = tid
                new_trades.append(t)
                open_assets.add(asset)
                risk = J.risk_status(conn, now)
        if asset in open_assets and status != "SIGNAL":
            status = "IN TRADE"
        elif not session:
            status = "OUT OF SESSION"
        watch.append({"asset": asset, "status": status, "detail": " | ".join(notes)})

    for w in watch:
        conn.execute("INSERT OR REPLACE INTO watchlist VALUES (?, ?, ?, ?)", (w["asset"], w["status"], w["detail"], J.iso(now)))
    conn.commit()
    return {"new_trades": new_trades, "watchlist": watch, "risk": risk, "session": session, "rule_version": version}


def run_cycle(conn, provider=None, now: datetime | None = None) -> dict:
    provider = provider or YahooProvider()
    now = now or J.utcnow()
    resolved = resolve_due(conn, provider, now)
    out = scan(conn, provider, now)
    out["resolved"] = resolved
    J.set_meta(conn, "heartbeat", J.iso(now))
    return out
