import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def make_df(n=400, freq="5min", seed=0, end="2026-10-09 13:00", drift=0.0):
    rng = np.random.default_rng(seed)
    close = 1.10 + np.cumsum(rng.normal(drift, 0.0004, n))
    open_ = np.r_[close[0], close[:-1]]
    hi = np.maximum(open_, close) + rng.uniform(0, 0.0003, n)
    lo = np.minimum(open_, close) - rng.uniform(0, 0.0003, n)
    idx = pd.date_range(end=pd.Timestamp(end, tz="UTC"), periods=n, freq=freq)
    return pd.DataFrame({"open": open_, "high": hi, "low": lo, "close": close}, index=idx)


class FakeProvider:
    """Serves synthetic candles; drops bars that have not closed yet, like the live feed."""
    def __init__(self, frames):
        self.frames = frames

    def candles(self, symbol, interval, now, range_=None):
        df = self.frames[interval]
        iv = pd.Timedelta(minutes=1 if interval == "1m" else 5)
        return df[df.index + iv <= now]


@pytest.fixture
def conn(tmp_path):
    from iqlab import journal
    return journal.connect(tmp_path / "t.db")
