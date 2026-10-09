"""Central settings. Override any value with environment variables (IQLAB_*)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("IQLAB_DB", ROOT / "data" / "iqlab.db"))

# IQ Option asset name -> Yahoo Finance symbol used as the price feed.
# Only regular-market assets: OTC prices are IQ's own feed and cannot be verified.
ASSETS = {
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "JPY=X",
    "EUR/JPY": "EURJPY=X",
    "Gold": "GC=F",
}

TZ = "Asia/Bangkok"
# Trading window in Thai local hours [start, end). London-NY overlap by default.
SESSION_HOURS = tuple(int(x) for x in os.environ.get("IQLAB_SESSION", "19,23").split(","))

DEMO_BALANCE = float(os.environ.get("IQLAB_BALANCE", 10_000))
STAKE_PCT = float(os.environ.get("IQLAB_STAKE_PCT", 0.01))       # 1% per trade
DEFAULT_PAYOUT = float(os.environ.get("IQLAB_PAYOUT", 0.85))     # assumed when IQ payout unknown
MIN_PAYOUT = 0.80

# Risk rules (applied in demo too, so the research matches how real money would trade)
MAX_TRADES_PER_DAY = int(os.environ.get("IQLAB_MAX_TRADES", 25))
MAX_CONSEC_LOSSES = 3
DAILY_LOSS_LIMIT_PCT = 0.03
DAILY_PROFIT_LOCK_PCT = 0.05
ENFORCE_DAILY_STOPS = os.environ.get("IQLAB_ENFORCE_STOPS", "1") == "1"

# Statistical gate before any real money
GATE_MIN_TRADES = 500
GATE_MIN_WINRATE = 0.58

SIGNAL_MAX_AGE_SEC = 90           # a signal older than this is stale for execution on IQ
SHEETS_WEBHOOK = os.environ.get("IQLAB_SHEETS_WEBHOOK", "")
DASHBOARD_PORT = int(os.environ.get("IQLAB_PORT", 8765))


def breakeven_winrate(payout: float = DEFAULT_PAYOUT) -> float:
    return 1 / (1 + payout)
