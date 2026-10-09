"""CLI: python -m iqlab {run,dashboard,backtest,mcp,stats,rules}"""
import argparse
import json
import logging
import threading
import time

from . import config, journal as J


def main():
    ap = argparse.ArgumentParser(prog="iqlab")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="scan loop every N seconds + dashboard + Sheets sync")
    r.add_argument("--every", type=int, default=60)
    r.add_argument("--no-dashboard", action="store_true")
    sub.add_parser("dashboard")
    b = sub.add_parser("backtest")
    b.add_argument("--session-only", action="store_true")
    b.add_argument("--csv", default=str(config.ROOT / "data" / "backtest.csv"))
    sub.add_parser("mcp")
    s = sub.add_parser("stats")
    s.add_argument("--scope", default="paper", choices=["paper", "iq"])
    ru = sub.add_parser("rules")
    ru.add_argument("action", choices=["list", "approve", "reject"])
    ru.add_argument("version", nargs="?", type=int)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    if a.cmd == "run":
        from . import engine, sheets
        if not a.no_dashboard:
            from . import dashboard
            threading.Thread(target=dashboard.serve, daemon=True).start()
        conn = J.connect()
        while True:
            try:
                out = engine.run_cycle(conn)
                for t in out["new_trades"]:
                    logging.info("SIGNAL #%s %s %s %s %sm conf %.2f", t["id"], t["asset"], t["direction"],
                                 t["setup"], t["expiry_min"], t["confidence"])
                for x in out["resolved"]:
                    logging.info("RESOLVED #%s %s %s", x["id"], x["asset"], x["result"])
                if out["risk"]["blocked"]:
                    logging.info("risk: %s", out["risk"]["blocked"])
                sheets.sync(conn)
            except Exception as e:
                logging.exception("cycle failed: %s", e)
            time.sleep(a.every)
    elif a.cmd == "dashboard":
        from . import dashboard
        dashboard.serve()
    elif a.cmd == "backtest":
        from . import backtest
        df = backtest.run(session_only=a.session_only)
        config.Path(a.csv).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(a.csv, index=False)
        print(backtest.report(df))
        print(f"trades saved to {a.csv}")
    elif a.cmd == "mcp":
        from .server import main as serve_mcp
        serve_mcp()
    elif a.cmd == "stats":
        st = J.stats(J.connect(), a.scope)
        st.pop("equity")
        print(json.dumps(st, indent=2, ensure_ascii=False))
    elif a.cmd == "rules":
        conn = J.connect()
        if a.action == "list":
            for row in J.rows(conn.execute("SELECT version, status, reason, created_at FROM rule_versions")):
                print(row)
        else:
            J.set_rule_status(conn, a.version, a.action == "approve")
            print(f"v{a.version} {a.action}d")


if __name__ == "__main__":
    main()
