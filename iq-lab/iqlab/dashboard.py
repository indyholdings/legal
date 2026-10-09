"""Local live dashboard: http://localhost:8765 (reads the SQLite journal)."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config, journal as J

HTML = (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")


def state(conn) -> dict:
    now = J.utcnow()
    open_ = J.rows(conn.execute("SELECT * FROM trades WHERE status='OPEN' ORDER BY expiry_at"))
    for t in open_:
        t["sec_left"] = int((J.parse(t["expiry_at"]) - now).total_seconds())
    paper, iq = J.stats(conn, "paper"), J.stats(conn, "iq")
    version, _ = J.active_rules(conn)
    return {
        "now": J.iso(now), "heartbeat": J.get_meta(conn, "heartbeat"), "rule_version": version,
        "risk": J.risk_status(conn, now), "open": open_,
        "recent": J.rows(conn.execute("SELECT * FROM trades WHERE status!='OPEN' ORDER BY expiry_at DESC LIMIT 25")),
        "watchlist": J.rows(conn.execute("SELECT * FROM watchlist ORDER BY asset")),
        "paper": paper, "iq": {k: iq[k] for k in ("n", "winrate", "wr_lower95", "pnl", "gate")},
        "review": J.rows(conn.execute("SELECT * FROM reviews ORDER BY date DESC LIMIT 1")),
        "session_hours": config.SESSION_HOURS,
    }


def serve(port: int | None = None) -> None:
    conn = J.connect()

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/api/state"):
                body, ctype = json.dumps(state(conn)).encode(), "application/json"
            else:
                body, ctype = HTML.encode(), "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    port = port or config.DASHBOARD_PORT
    print(f"dashboard: http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
