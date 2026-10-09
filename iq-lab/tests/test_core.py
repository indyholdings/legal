from datetime import timedelta

import pandas as pd
import pytest

from conftest import FakeProvider, make_df
from iqlab import backtest, config, engine, indicators as ind, journal as J
from iqlab.rules import DEFAULT_RULES
from iqlab.strategies import STRATEGIES


def test_indicators_ranges():
    df = make_df()
    r = ind.rsi(df["close"])
    assert r.between(0, 100).all()
    assert (ind.adx(df) >= 0).all()
    lo, mid, hi = ind.bollinger(df["close"])
    assert (lo.dropna() <= hi.dropna()).all()


@pytest.mark.parametrize("setup", list(STRATEGIES))
def test_strategies_shape_and_no_lookahead(setup):
    p = DEFAULT_RULES[setup]
    df = make_df(800, freq="1min" if p["tf"] == "1m" else "5min", seed=3)
    full = STRATEGIES[setup](df, p)
    assert set(full["direction"].unique()) <= {"", "CALL", "PUT"}
    # signal on bar i must not change when later bars are appended
    cut = STRATEGIES[setup](df.iloc[:600], p)
    pd.testing.assert_frame_equal(full.iloc[:600], cut)


def test_strategies_fire_on_random_walk():
    fired = 0
    for setup, p in DEFAULT_RULES.items():
        df = make_df(3000, freq="1min" if p["tf"] == "1m" else "5min", seed=7)
        fired += (STRATEGIES[setup](df, p)["direction"] != "").sum()
    assert fired > 0


def test_outcome_and_pnl():
    assert J.outcome("CALL", 1.0, 1.1) == "WIN"
    assert J.outcome("PUT", 1.0, 1.1) == "LOSS"
    assert J.outcome("PUT", 1.0, 1.0) == "TIE"
    assert J.pnl_for("WIN", 100, 0.85) == 85.0
    assert J.pnl_for("LOSS", 100, 0.85) == -100


def test_wilson_and_gate():
    assert J.wilson_lower(0, 0) == 0
    lb = J.wilson_lower(290, 500)  # 58%
    assert 0.54 < lb < 0.58
    assert J.wilson_lower(174, 300) < config.breakeven_winrate()  # 58% of 300 is NOT enough
    be = config.breakeven_winrate()
    assert J.gate(500, 290, be)["passed"]
    assert not J.gate(300, 174, be)["passed"]


def _trade(i, now, status=None, asset="EUR/USD", direction="CALL"):
    return {"signal_key": f"k{i}", "created_at": J.iso(now), "asset": asset, "symbol": "EURUSD=X",
            "direction": direction, "setup": "S1_trend_pullback", "tf": "5m", "expiry_min": 15,
            "entry_at": J.iso(now), "expiry_at": J.iso(now + timedelta(minutes=15)), "entry_price": 1.0,
            "stake": 100.0, "payout": 0.85, "confidence": 0.6, "rule_version": 1, "regime": "range", "reason": "t"}


def test_journal_roundtrip_and_risk(conn):
    now = J.utcnow()
    ids = [J.open_trade(conn, _trade(i, now)) for i in range(4)]
    assert J.open_trade(conn, _trade(0, now)) is None  # dedupe
    J.resolve_trade(conn, ids[0], 1.1)
    for i in ids[1:]:
        J.resolve_trade(conn, i, 0.9)
    st = J.stats(conn)
    assert (st["wins"], st["losses"], st["pnl"]) == (1, 3, -215.0)
    risk = J.risk_status(conn, now)
    assert risk["consec_losses"] == 3 and "losses in a row" in risk["blocked"]
    J.record_iq_result(conn, ids[0], "loss")
    assert J.stats(conn, "iq")["losses"] == 1


def test_rules_versioning(conn):
    v = J.propose_rules(conn, {"S2_mean_reversion": {"adx_max": 18}}, "test")
    assert J.active_rules(conn)[0] == 1
    J.set_rule_status(conn, v, True)
    ver, rules = J.active_rules(conn)
    assert ver == v and rules["S2_mean_reversion"]["adx_max"] == 18
    with pytest.raises(ValueError):
        J.propose_rules(conn, {"S2_mean_reversion": {"nope": 1}}, "bad")


def _session_now():
    # 20:30 Thai time = 13:30 UTC, inside the default 19-23 session
    return pd.Timestamp("2026-10-09 13:30", tz="UTC").to_pydatetime()


def test_engine_cycle_journals_and_resolves(conn, monkeypatch):
    # make every setup fire on every bar so the cycle definitely opens trades
    always = lambda df, p: pd.DataFrame({"direction": "CALL", "confidence": 0.7}, index=df.index)
    monkeypatch.setattr(engine, "STRATEGIES", {k: always for k in DEFAULT_RULES})
    f1 = make_df(600, "1min", end="2026-10-09 14:30")
    f5 = make_df(400, "5min", end="2026-10-09 14:30")
    prov = FakeProvider({"1m": f1, "5m": f5})
    now = _session_now()
    out = engine.run_cycle(conn, prov, now)
    assert len(out["new_trades"]) == len(config.ASSETS)          # one per asset (one open trade per asset)
    assert {w["status"] for w in out["watchlist"]} == {"SIGNAL"}
    again = engine.run_cycle(conn, prov, now)
    assert again["new_trades"] == []                               # no duplicates while trades are open
    later = now + timedelta(minutes=30)
    res = engine.run_cycle(conn, prov, later)
    assert len(res["resolved"]) == len(config.ASSETS)
    assert all(r["result"] in ("WIN", "LOSS", "TIE") for r in res["resolved"])


def test_engine_respects_session_and_blackout(conn, monkeypatch):
    always = lambda df, p: pd.DataFrame({"direction": "PUT", "confidence": 0.7}, index=df.index)
    monkeypatch.setattr(engine, "STRATEGIES", {k: always for k in DEFAULT_RULES})
    prov = FakeProvider({"1m": make_df(600, "1min", end="2026-10-09 06:00"),
                         "5m": make_df(400, "5min", end="2026-10-09 06:00")})
    out = engine.run_cycle(conn, prov, pd.Timestamp("2026-10-09 05:00", tz="UTC").to_pydatetime())  # 12:00 TH
    assert out["new_trades"] == [] and not out["session"]
    now = _session_now()
    conn.execute("INSERT INTO blackouts (start_utc,end_utc,label) VALUES (?,?,?)",
                 (J.iso(now - timedelta(minutes=5)), J.iso(now + timedelta(minutes=5)), "NFP"))
    prov2 = FakeProvider({"1m": make_df(600, "1min", end="2026-10-09 14:30"),
                          "5m": make_df(400, "5min", end="2026-10-09 14:30")})
    assert engine.run_cycle(conn, prov2, now)["new_trades"] == []


def test_backtest_runs_offline():
    frames = {}
    for sym in config.ASSETS.values():
        frames[(sym, "1m")] = make_df(3000, "1min", seed=1)
        frames[(sym, "5m")] = make_df(3000, "5min", seed=2)
    df = backtest.run(DEFAULT_RULES, frames=frames)
    assert not df.empty and set(df["result"]) <= {"WIN", "LOSS", "TIE"}
    assert "breakeven" in backtest.report(df)


def test_mcp_server_imports(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "s.db")
    from iqlab import server
    assert server.get_rules()["active_version"] == 1
    assert server.get_executable_signals() == []
