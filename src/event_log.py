# Class 9 - event log for the dashboard

from __future__ import annotations

import os
import time
import json
import sqlite3
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DB = str(HERE.parent / "data" / "events.db")


class EventLog:

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.getenv("EVENT_DB", DEFAULT_DB)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts                 REAL    NOT NULL,
                    account_id         TEXT,
                    amount             REAL,
                    severity           TEXT,
                    z_basis            TEXT,
                    account_z          REAL,
                    global_z           REAL,
                    account_mean       REAL,
                    account_n          INTEGER,
                    account_warm       INTEGER,
                    txn_count_1h       INTEGER,
                    ml_flagged         INTEGER,
                    ml_score           REAL,
                    reason             TEXT,
                    alert_sent         INTEGER DEFAULT 0,
                    suppressed         INTEGER DEFAULT 0,
                    suppression_reason TEXT,
                    dedup_key          TEXT,
                    true_fraud         INTEGER
                )
            """)
            cols = {r[1] for r in self.conn.execute("PRAGMA table_info(events)")}
            if "true_fraud" not in cols:
                self.conn.execute("ALTER TABLE events ADD COLUMN true_fraud INTEGER")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")
            self.conn.commit()

    def record(self, result: dict, alert: dict | None = None) -> int:
        alert = alert or {}
        with self._lock:
            cur = self.conn.execute("""
                INSERT INTO events (ts, account_id, amount, severity, z_basis,
                    account_z, global_z, account_mean, account_n, account_warm,
                    txn_count_1h, ml_flagged, ml_score, reason,
                    alert_sent, suppressed, suppression_reason, dedup_key,
                    true_fraud)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                time.time(),
                result.get("account_id"),
                result.get("Amount"),
                result.get("severity"),
                result.get("z_basis"),
                result.get("account_z"),
                result.get("global_z"),
                result.get("account_mean"),
                result.get("account_n"),
                1 if result.get("account_warm") else 0,
                result.get("txn_count_1h"),
                1 if result.get("ml_flagged") else 0,
                result.get("ml_score"),
                result.get("reason"),
                # Only count it as sent if it actually went, or if delivery was
                # deliberately handed to n8n. A failed send is NOT a sent alert.
                1 if (alert.get("sent")
                      or alert.get("delivered_by") == "n8n") else 0,
                1 if alert.get("suppressed") else 0,
                alert.get("suppression_reason"),
                alert.get("dedup_key"),
                (int(result["true_fraud"])
                 if result.get("true_fraud") is not None else None),
            ))
            self.conn.commit()
            return cur.lastrowid

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def summary(self) -> dict:
        with self._lock:
            r = self.conn.execute("""
                SELECT COUNT(*)                                      AS total,
                       COALESCE(SUM(severity='high'), 0)             AS high,
                       COALESCE(SUM(severity='medium'), 0)           AS medium,
                       COALESCE(SUM(severity='normal'), 0)           AS normal,
                       COALESCE(SUM(alert_sent), 0)                  AS sent,
                       COALESCE(SUM(suppressed), 0)                  AS suppressed,
                       COALESCE(SUM(account_warm), 0)                AS warm,
                       COUNT(DISTINCT account_id)                    AS accounts
                FROM events
            """).fetchone()
        d = dict(r)
        alertable = d["high"] + d["medium"]
        d["alertable"] = alertable
        d["suppression_rate"] = (
            round(d["suppressed"] / alertable * 100, 1) if alertable else 0.0
        )

        # Ground truth. Only meaningful when replaying labelled data - a
        # generated stream has no true_fraud column and these stay at zero.
        with self._lock:
            g = self.conn.execute("""
                SELECT
                  COALESCE(SUM(true_fraud = 1), 0)                          AS actual_fraud,
                  COALESCE(SUM(true_fraud = 1 AND severity != 'normal'), 0) AS caught,
                  COALESCE(SUM(true_fraud = 0 AND severity != 'normal'), 0) AS false_alarm,
                  COALESCE(SUM(true_fraud = 1 AND severity  = 'normal'), 0) AS missed,
                  COALESCE(SUM(true_fraud IS NOT NULL), 0)                  AS labelled
                FROM events
            """).fetchone()

        d.update(dict(g))
        flagged = d["caught"] + d["false_alarm"]
        d["recall"] = (round(d["caught"] / d["actual_fraud"] * 100, 1)
                       if d["actual_fraud"] else 0.0)
        d["precision"] = (round(d["caught"] / flagged * 100, 1)
                          if flagged else 0.0)
        d["has_labels"] = bool(d["labelled"])
        return d

    def clear(self) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM events")
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.commit()
            self.conn.close()
