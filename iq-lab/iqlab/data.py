"""Price feed. Uses Yahoo Finance's public chart endpoint (no API key).

IQ Option's own quotes can differ by a few pips from this feed; trades executed on
IQ record their real result separately (iq_result) so the gap is measurable.
"""
from __future__ import annotations

import pandas as pd
import requests

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
INTERVAL_SEC = {"1m": 60, "5m": 300}
LIVE_RANGE = {"1m": "1d", "5m": "5d"}
MAX_RANGE = {"1m": "7d", "5m": "60d"}


def fetch_candles(symbol: str, interval: str, range_: str, timeout: int = 15) -> pd.DataFrame:
    r = requests.get(
        YAHOO_URL.format(symbol=symbol),
        params={"interval": interval, "range": range_, "includePrePost": "false"},
        headers={"User-Agent": "Mozilla/5.0 (iq-lab research)"},
        timeout=timeout,
    )
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame(
        {k: q[k] for k in ("open", "high", "low", "close")},
        index=pd.to_datetime(res.get("timestamp", []), unit="s", utc=True),
    )
    return df.dropna().astype(float)


def drop_incomplete(df: pd.DataFrame, interval: str, now: pd.Timestamp) -> pd.DataFrame:
    """Keep only bars whose close time has passed."""
    iv = pd.Timedelta(seconds=INTERVAL_SEC[interval])
    return df[df.index + iv <= now]


class YahooProvider:
    def candles(self, symbol: str, interval: str, now: pd.Timestamp, range_: str | None = None) -> pd.DataFrame:
        df = fetch_candles(symbol, interval, range_ or LIVE_RANGE[interval])
        return drop_incomplete(df, interval, now)
