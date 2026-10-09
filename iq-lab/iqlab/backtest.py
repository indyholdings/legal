"""Backtest the active rules on recent history (Yahoo: 7 days of 1m, 60 days of 5m).

Same signal code as live. Entry = close of the signal bar, exit = close of the bar that
ends at entry + expiry. One open trade per asset at a time. Gives a first read on each
setup in minutes instead of weeks of demo trading - but history != future, so the demo
run and the 500-trade gate still decide."""
from __future__ import annotations

import pandas as pd

from . import config, journal as J
from .data import INTERVAL_SEC, MAX_RANGE, fetch_candles
from .strategies import STRATEGIES, market_context  # noqa: F401


def simulate(df: pd.DataFrame, setup: str, p: dict, asset: str) -> list[dict]:
    sig = STRATEGIES[setup](df, p)
    iv = pd.Timedelta(seconds=INTERVAL_SEC[p["tf"]])
    exp = pd.Timedelta(minutes=p["expiry_min"])
    close = df["close"]
    out, busy_until = [], None
    for ts in sig.index[sig["direction"] != ""]:
        entry_at = ts + iv
        if busy_until is not None and entry_at < busy_until:
            continue
        exit_bar = ts + exp
        if exit_bar not in close.index:
            continue
        d = sig.at[ts, "direction"]
        res = J.outcome(d, close[ts], close[exit_bar])
        busy_until = entry_at + exp
        out.append({"asset": asset, "setup": setup, "direction": d, "entry_at": entry_at,
                    "hour_th": entry_at.tz_convert(config.TZ).hour, "entry": close[ts],
                    "exit": close[exit_bar], "result": res, "confidence": sig.at[ts, "confidence"]})
    return out


def run(rules: dict | None = None, session_only: bool = False, frames: dict | None = None) -> pd.DataFrame:
    """frames: optional {(symbol, tf): df} to skip downloading (tests)."""
    if rules is None:
        conn = J.connect()
        _, rules = J.active_rules(conn)
    trades = []
    for asset, symbol in config.ASSETS.items():
        for setup, p in rules.items():
            if not p.get("enabled"):
                continue
            key = (symbol, p["tf"])
            if frames is None or key not in frames:
                frames = frames or {}
                frames[key] = fetch_candles(symbol, p["tf"], MAX_RANGE[p["tf"]])
            trades += simulate(frames[key], setup, p, asset)
    df = pd.DataFrame(trades)
    if session_only and not df.empty:
        s, e = config.SESSION_HOURS
        df = df[(df["hour_th"] >= s) & (df["hour_th"] < e)]
    return df


def report(df: pd.DataFrame) -> str:
    if df.empty:
        return "no trades"
    be = config.breakeven_winrate()
    lines = [f"breakeven winrate @ payout {config.DEFAULT_PAYOUT:.0%}: {be:.1%}", ""]

    def block(title, g):
        lines.append(f"{title:<28}{'n':>6}{'win%':>8}{'low95':>8}  edge?")
        for k, sub in g:
            w, n = (sub["result"] == "WIN").sum(), sub["result"].isin(["WIN", "LOSS"]).sum()
            if n == 0:
                continue
            lb = J.wilson_lower(int(w), int(n))
            flag = "YES" if lb > be else ("maybe" if w / n > be else "no")
            lines.append(f"{str(k):<28}{n:>6}{w / n:>8.1%}{lb:>8.1%}  {flag}")
        lines.append("")

    block("ALL", [("all", df)])
    block("setup", df.groupby("setup"))
    block("setup x asset", df.groupby(["setup", "asset"]))
    block("hour (TH)", df.groupby("hour_th"))
    return "\n".join(lines)
