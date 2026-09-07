# Class 7 - per-account behavioural baselines

from __future__ import annotations

import os
import json
import math
import time
import sqlite3
import threading
from dataclasses import dataclass, asdict
from pathlib import Path


MIN_HISTORY = 30

EWMA_ALPHA = 0.05

VELOCITY_WINDOW = 3600
MAX_TRACKED_TIMESTAMPS = 64

MIN_STD = 1e-6
MIN_STD_FRACTION = 0.01

Z_CAP = 999.0

# Class 10
ESCALATE_AT = int(os.getenv("ESCALATE_AT", "1"))
REQUIRE_ML = os.getenv("REQUIRE_ML", "1") not in ("0", "false", "False")


def _clamp_z(z: float) -> float:
    return max(-Z_CAP, min(Z_CAP, z))


LOG_SPACE = os.getenv("BASELINE_LOG_SPACE", "1") not in ("0", "false", "False")


def to_space(amount: float, log_space: bool) -> float:
    return math.log1p(max(amount, 0.0)) if log_space else amount


@dataclass
class AccountState:
    account_id: str
    n: int = 0
    mean: float = 0.0
    m2: float = 0.0
    ewma_mean: float = 0.0
    ewma_var: float = 0.0
    last_ts: float | None = None
    recent_ts: list[float] = None

    def __post_init__(self):
        if self.recent_ts is None:
            self.recent_ts = []

    @property
    def variance(self) -> float:
        return self.m2 / (self.n - 1) if self.n > 1 else 0.0

    @property
    def std(self) -> float:
        return math.sqrt(max(self.variance, 0.0))

    @property
    def ewma_std(self) -> float:
        return math.sqrt(max(self.ewma_var, 0.0))

    @property
    def effective_std(self) -> float:
        return max(self.std, MIN_STD_FRACTION * abs(self.mean), MIN_STD)

    @property
    def effective_ewma_std(self) -> float:
        return max(self.ewma_std, MIN_STD_FRACTION * abs(self.ewma_mean), MIN_STD)

    @property
    def is_warm(self) -> bool:
        return self.n >= MIN_HISTORY

    def update(self, amount: float, ts: float) -> None:
        self.n += 1
        delta = amount - self.mean
        self.mean += delta / self.n
        self.m2 += delta * (amount - self.mean)

        if self.n == 1:
            self.ewma_mean = amount
            self.ewma_var = 0.0
        else:
            diff = amount - self.ewma_mean
            incr = EWMA_ALPHA * diff
            self.ewma_mean += incr
            self.ewma_var = (1 - EWMA_ALPHA) * (self.ewma_var + diff * incr)

        self.last_ts = ts
        self.recent_ts.append(ts)
        cutoff = ts - VELOCITY_WINDOW
        self.recent_ts = [t for t in self.recent_ts if t >= cutoff][-MAX_TRACKED_TIMESTAMPS:]


class BaselineStore:

    def __init__(self, db_path: str = "../data/baselines.db",
                 global_mean: float = 0.0, global_std: float = 1.0,
                 log_space: bool | None = None):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.log_space = LOG_SPACE if log_space is None else log_space
        self.global_mean = global_mean
        self.global_std = max(global_std, MIN_STD)
        self._lock = threading.RLock()
        try:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self._init_schema()
        except sqlite3.OperationalError as e:
            if "disk I/O error" in str(e) or "unable to open" in str(e):
                raise sqlite3.OperationalError(
                    f"cannot open {self.db_path!r} (no file locking on this "
                    f"filesystem) - set BASELINE_DB to a local path"
                ) from e
            raise

    def _init_schema(self) -> None:
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS account_baselines (
                account_id  TEXT PRIMARY KEY,
                n           INTEGER NOT NULL DEFAULT 0,
                mean        REAL    NOT NULL DEFAULT 0.0,
                m2          REAL    NOT NULL DEFAULT 0.0,
                ewma_mean   REAL    NOT NULL DEFAULT 0.0,
                ewma_var    REAL    NOT NULL DEFAULT 0.0,
                last_ts     REAL,
                recent_ts   TEXT    NOT NULL DEFAULT '[]',
                updated_at  REAL    NOT NULL DEFAULT 0.0
            )
        """)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS store_meta (key TEXT PRIMARY KEY, value TEXT)")
        self.conn.commit()

        want = "log1p" if self.log_space else "raw"
        row = self.conn.execute(
            "SELECT value FROM store_meta WHERE key='space'").fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO store_meta (key, value) VALUES ('space', ?)", (want,))
            self.conn.commit()
        elif row["value"] != want:
            raise ValueError(
                f"db is '{row['value']}' space, store is '{want}' - "
                f"delete the db or set BASELINE_LOG_SPACE="
                f"{'1' if row['value'] == 'log1p' else '0'}"
            )

    def load(self, account_id: str) -> AccountState:
        row = self.conn.execute(
            "SELECT * FROM account_baselines WHERE account_id = ?", (account_id,)
        ).fetchone()
        if row is None:
            return AccountState(account_id=account_id)
        return AccountState(
            account_id=row["account_id"], n=row["n"], mean=row["mean"], m2=row["m2"],
            ewma_mean=row["ewma_mean"], ewma_var=row["ewma_var"],
            last_ts=row["last_ts"], recent_ts=json.loads(row["recent_ts"]),
        )

    def save(self, st: AccountState) -> None:
        self.conn.execute("""
            INSERT INTO account_baselines
                (account_id, n, mean, m2, ewma_mean, ewma_var, last_ts, recent_ts, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(account_id) DO UPDATE SET
                n=excluded.n, mean=excluded.mean, m2=excluded.m2,
                ewma_mean=excluded.ewma_mean, ewma_var=excluded.ewma_var,
                last_ts=excluded.last_ts, recent_ts=excluded.recent_ts,
                updated_at=excluded.updated_at
        """, (st.account_id, st.n, st.mean, st.m2, st.ewma_mean, st.ewma_var,
              st.last_ts, json.dumps(st.recent_ts), time.time()))

    def commit(self) -> None:
        self.conn.commit()

    def features(self, account_id: str, amount: float, ts: float) -> dict:
        st = self.load(account_id)

        global_z = (amount - self.global_mean) / self.global_std

        x = to_space(amount, self.log_space)

        cutoff = ts - VELOCITY_WINDOW
        recent = [t for t in st.recent_ts if t >= cutoff]
        seconds_since_last = (ts - st.last_ts) if st.last_ts is not None else None

        out = {
            "account_id": account_id,
            "account_n": st.n,
            "account_warm": st.is_warm,
            "space": "log1p" if self.log_space else "raw",
            "global_z": round(global_z, 4),
            "txn_count_1h": len(recent),
            "seconds_since_last": (round(seconds_since_last, 1)
                                   if seconds_since_last is not None else None),
            "account_z": None,
            "account_ewma_z": None,
            "account_mean": None,
            "account_std": None,
            "baseline_drift": None,
        }

        if st.is_warm:
            std = st.effective_std
            out["account_z"] = round(_clamp_z((x - st.mean) / std), 4)
            out["account_mean"] = round(
                math.expm1(st.mean) if self.log_space else st.mean, 2)
            out["account_std"] = round(std, 4)

            estd = st.effective_ewma_std
            out["account_ewma_z"] = round(_clamp_z((x - st.ewma_mean) / estd), 4)

            out["baseline_drift"] = round(_clamp_z((st.ewma_mean - st.mean) / std), 4)

        return out

    def observe(self, account_id: str, amount: float, ts: float,
                autocommit: bool = True) -> dict:
        with self._lock:
            feats = self.features(account_id, amount, ts)
            st = self.load(account_id)
            st.update(to_space(amount, self.log_space), ts)
            self.save(st)
            if autocommit:
                self.commit()
            return feats

    def warm_up(self, rows, autocommit: bool = True) -> int:
        count = 0
        for account_id, amount, ts in rows:
            st = self.load(account_id)
            st.update(to_space(float(amount), self.log_space), float(ts))
            self.save(st)
            count += 1
        if autocommit:
            self.commit()
        return count

    def stats(self) -> dict:
        r = self.conn.execute("""
            SELECT COUNT(*) AS accounts,
                   COALESCE(SUM(n), 0) AS transactions,
                   COALESCE(AVG(n), 0) AS avg_history,
                   COALESCE(SUM(CASE WHEN n >= ? THEN 1 ELSE 0 END), 0) AS warm
            FROM account_baselines
        """, (MIN_HISTORY,)).fetchone()
        return {
            "accounts": r["accounts"],
            "transactions_seen": r["transactions"],
            "avg_history_per_account": round(r["avg_history"], 1),
            "warm_accounts": r["warm"],
            "cold_accounts": r["accounts"] - r["warm"],
            "min_history_threshold": MIN_HISTORY,
            "db_size_bytes": (Path(self.db_path).stat().st_size
                              if self.db_path != ":memory:" and Path(self.db_path).exists()
                              else None),
        }

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()


def combine_severity(account_z, global_z, txn_count_1h, ml_flagged,
                     account_warm, min_signals: int | None = None,
                     require_ml: bool | None = None) -> tuple[str, list[str]]:
    if min_signals is None:
        min_signals = ESCALATE_AT
    if require_ml is None:
        require_ml = REQUIRE_ML
    reasons: list[str] = []
    z = account_z if (account_warm and account_z is not None) else global_z
    z_label = "vs own history" if (account_warm and account_z is not None) else "vs all accounts"

    amount_odd = z is not None and z > 3
    if amount_odd:
        reasons.append(f"amount z-score {z:.2f} {z_label}")

    velocity_odd = txn_count_1h >= 10
    if velocity_odd:
        reasons.append(f"{txn_count_1h} transactions in the last hour (possible card testing)")

    if ml_flagged:
        reasons.append("isolation forest flagged the transaction")

    if not account_warm:
        reasons.append("account has insufficient history - scored against global baseline")

    signals = sum([amount_odd, velocity_odd, bool(ml_flagged)])

    if require_ml:
        if not ml_flagged:
            severity = "normal"
        elif signals >= 2:
            severity = "high"
        else:
            severity = "medium"
    elif signals >= min_signals + 1:
        severity = "high"
    elif signals >= min_signals:
        severity = "medium"
    else:
        severity = "normal"

    if severity == "normal" and signals:
        why = ("isolation forest did not flag it" if require_ml
               else f"{signals} of {min_signals} required signals")
        reasons.append(f"not escalated - {why}")

    return severity, reasons