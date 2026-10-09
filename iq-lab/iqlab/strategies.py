"""Rule-based setups. Each returns, for every bar, a direction ('CALL'/'PUT'/'')
decided at that bar's close, plus a 0-1 confidence score. Vectorised so the same
code drives live scanning (last closed bar) and backtests (all bars)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as ind


def _out(call: pd.Series, put: pd.Series, conf: pd.Series) -> pd.DataFrame:
    direction = np.where(call, "CALL", np.where(put, "PUT", ""))
    return pd.DataFrame({"direction": direction, "confidence": conf.clip(0, 1).round(3)}, index=call.index)


def s1_trend_pullback(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    c, o, h, l = df["close"], df["open"], df["high"], df["low"]
    fast, slow = ind.ema(c, p["ema_fast"]), ind.ema(c, p["ema_slow"])
    a = ind.atr(df)
    r = ind.rsi(c, 14)
    up = slow > slow.shift(p["slope_bars"])
    dn = slow < slow.shift(p["slope_bars"])
    tol = p["touch_tol_atr"] * a
    touched_up = l.shift(1) <= fast.shift(1) + tol.shift(1)      # previous bar pulled back to fast EMA
    touched_dn = h.shift(1) >= fast.shift(1) - tol.shift(1)
    mid = p["rsi_mid"]
    call = (up & (c > slow) & touched_up & (c > h.shift(1)) & (r.shift(1) < mid) & (r >= mid)
            & r.between(p["rsi_min"], p["rsi_max"]))
    put = (dn & (c < slow) & touched_dn & (c < l.shift(1)) & (r.shift(1) > 100 - mid) & (r <= 100 - mid)
           & r.between(100 - p["rsi_max"], 100 - p["rsi_min"]))
    conf = 0.5 + 0.3 * (ind.adx(df) / 40).clip(0, 1)
    warm = pd.Series(np.arange(len(df)) >= p["ema_slow"], index=df.index)
    return _out(call & warm, put & warm, conf)


def s2_mean_reversion(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    c = df["close"]
    lo, mid, hi = ind.bollinger(c, p["bb_n"], p["bb_k"])
    r2 = ind.rsi(c, 2)
    ax = ind.adx(df)
    ranging = ax < p["adx_max"]
    call = (c < lo) & (r2 < p["rsi2_low"]) & ranging
    put = (c > hi) & (r2 > p["rsi2_high"]) & ranging
    stretch = ((lo - c).clip(lower=0) + (c - hi).clip(lower=0)) / ind.atr(df).replace(0, np.nan)
    conf = 0.5 + 0.2 * stretch.fillna(0).clip(0, 1.5)
    return _out(call.fillna(False), put.fillna(False), conf)


def s3_sr_rejection(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    c, o, h, l = df["close"], df["open"], df["high"], df["low"]
    a = ind.atr(df)
    support = l.rolling(p["lookback"]).min().shift(3)
    resist = h.rolling(p["lookback"]).max().shift(3)
    body = (c - o).abs().clip(lower=1e-12)
    rng = (h - l).replace(0, np.nan)
    low_wick = np.minimum(o, c) - l
    up_wick = h - np.maximum(o, c)
    near = p["near_atr"] * a
    call = (low_wick >= p["wick_ratio"] * body) & (low_wick >= 0.5 * rng) & ((l - support).abs() <= near) & (c > support)
    put = (up_wick >= p["wick_ratio"] * body) & (up_wick >= 0.5 * rng) & ((h - resist).abs() <= near) & (c < resist)
    wick = pd.concat([low_wick, up_wick], axis=1).max(axis=1) / rng
    conf = 0.45 + 0.4 * wick.fillna(0).clip(0, 1)
    return _out(call.fillna(False), put.fillna(False), conf)


STRATEGIES = {
    "S1_trend_pullback": s1_trend_pullback,
    "S2_mean_reversion": s2_mean_reversion,
    "S3_sr_rejection": s3_sr_rejection,
}


def market_context(df5: pd.DataFrame) -> dict:
    """Short human-readable read of the market, for the watchlist."""
    if len(df5) < 60:
        return {"regime": "warming-up", "text": "not enough data"}
    c = df5["close"]
    slow = ind.ema(c, 50)
    ax = float(ind.adx(df5).iloc[-1])
    r = float(ind.rsi(c, 14).iloc[-1])
    trend = "up" if slow.iloc[-1] > slow.iloc[-4] else "down"
    regime = f"trend-{trend}" if ax >= 20 else "range"
    return {"regime": regime, "text": f"{regime} | ADX {ax:.0f} | RSI14 {r:.0f}"}
