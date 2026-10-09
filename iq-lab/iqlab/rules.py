"""Strategy parameters, versioned in the journal DB. v1 = these defaults."""
DEFAULT_RULES = {
    "S1_trend_pullback": {
        "enabled": True, "tf": "5m", "expiry_min": 15,
        "ema_fast": 20, "ema_slow": 50, "slope_bars": 3, "touch_tol_atr": 0.2,
        "rsi_mid": 50, "rsi_min": 40, "rsi_max": 65,
    },
    "S2_mean_reversion": {
        "enabled": True, "tf": "1m", "expiry_min": 5,
        "bb_n": 20, "bb_k": 2.5, "rsi2_low": 5, "rsi2_high": 95, "adx_max": 20,
    },
    "S3_sr_rejection": {
        "enabled": True, "tf": "5m", "expiry_min": 10,
        "lookback": 96, "wick_ratio": 2.0, "near_atr": 0.5,
    },
}
