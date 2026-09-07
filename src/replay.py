# Class 9 - replay real transactions from creditcard.csv

from __future__ import annotations

import os
import csv
import random
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Class 11 - the full 144MB dataset cannot go in git, so the deployed copy uses a
# stratified sample: every one of the 492 real frauds plus 25,000 normal rows.
FULL_CSV   = HERE.parent / "data" / "creditcard.csv"
SAMPLE_CSV = HERE.parent / "data" / "creditcard_sample.csv"
DEFAULT_CSV = str(FULL_CSV if FULL_CSV.exists() else SAMPLE_CSV)

FEATURE_COLS = [f"V{i}" for i in range(1, 29)]


class Replay:

    def __init__(self, csv_path: str | None = None, n_accounts: int = 8,
                 fraud_boost: int = 40, seed: int = 42,
                 seconds_between: float = 120.0):
        self.csv_path = csv_path or os.getenv("REPLAY_CSV", DEFAULT_CSV)
        self.n_accounts = n_accounts
        self.fraud_boost = fraud_boost
        self.seconds_between = seconds_between
        self._lock = threading.RLock()
        self._pos = 0
        self._clock = 0
        self._rows: list[dict] = []
        self._loaded = False
        self._seed = seed

    def _load(self) -> None:
        if self._loaded:
            return
        if not Path(self.csv_path).exists():
            raise FileNotFoundError(
                f"{self.csv_path} not found. Put creditcard.csv in data/ "
                f"(see data/README.md)"
            )

        normal, fraud = [], []
        with open(self.csv_path, newline="") as f:
            for row in csv.DictReader(f):
                rec = {
                    "Time": float(row["Time"]),
                    "Amount": float(row["Amount"]),
                    "true_fraud": int(row["Class"]),
                }
                for c in FEATURE_COLS:
                    rec[c] = float(row[c])
                (fraud if rec["true_fraud"] else normal).append(rec)

        rng = random.Random(self._seed)

        # The real fraud rate is 0.173% - about 1 in 578 transactions. At one
        # every 10 seconds a demo would run for 96 minutes before showing a
        # single fraud. So the stream is over-sampled: the same real fraud rows,
        # just scheduled more often. No row is invented or altered.
        keep_normal = min(len(normal), self.fraud_boost * len(fraud))
        stream = rng.sample(normal, keep_normal) + fraud
        rng.shuffle(stream)

        # creditcard.csv has no account column. IDs are assigned round-robin so
        # per-account baselines have something to group by. Amounts, features
        # and fraud labels are untouched.
        for i, rec in enumerate(stream):
            rec["account_id"] = f"CARD-{i % self.n_accounts:02d}"

        self._rows = stream
        self._loaded = True

    def nearest(self, amount: float) -> dict:
        """
        The real row from credit.csv whose Amount is closest to `amount`.

        A live checkout order has no V1-V28 PCA features - those only exist
        in the original bank data credit.csv was built from. This lets the
        trained model actually run against a real order by borrowing the
        feature vector of the closest real transaction by amount.
        """
        with self._lock:
            self._load()
            return dict(min(self._rows, key=lambda r: abs(r["Amount"] - amount)))

    def next(self) -> dict:
        with self._lock:
            self._load()
            rec = dict(self._rows[self._pos % len(self._rows)])
            self._pos += 1
            self._clock += 1
            rec["_row"] = self._pos
            # The rows are shuffled, so each row's original Time is out of order.
            # Feeding those to the velocity window makes "transactions in the last
            # hour" meaningless. Issue a monotonic arrival time instead.
            # Spacing is 120s so that with 8 accounts each one sees ~3.75
            # transactions per hour - below the velocity threshold of 10, which
            # is what a real small merchant looks like.
            # The clock is separate from the row position: reset() rewinds which
            # row comes next, but time never goes backwards, or the velocity
            # window would double count a replayed second run against the first.
            rec["Time"] = float(self._clock * self.seconds_between)
            return rec

    def stats(self) -> dict:
        with self._lock:
            self._load()
            frauds = sum(r["true_fraud"] for r in self._rows)
            return {
                "source": self.csv_path,
                "rows_in_stream": len(self._rows),
                "real_frauds_in_stream": frauds,
                "fraud_rate_pct": round(frauds / len(self._rows) * 100, 2),
                "position": self._pos,
                "arrival_clock": self._clock,
                "accounts": self.n_accounts,
                "note": "real amounts, features and fraud labels; "
                        "account ids assigned round-robin",
            }

    def reset(self, restart_clock: bool = False) -> None:
        with self._lock:
            self._pos = 0
            if restart_clock:
                self._clock = 0
