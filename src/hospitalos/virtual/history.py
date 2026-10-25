"""Durable observed hourly series and a chronological, auditable one-hour predictor."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from hospitalos.simulator.engine import Frame

PARIS = ZoneInfo("Europe/Paris")


class History:
    def __init__(self, path: str, capacity: int) -> None:
        self.capacity = capacity
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(
            "CREATE TABLE IF NOT EXISTS observations (at TEXT PRIMARY KEY, occupied INTEGER, "
            "waiting INTEGER, ready INTEGER);"
            "CREATE TABLE IF NOT EXISTS models (id INTEGER PRIMARY KEY, artifact TEXT);"
        )
        self.last_hour = ""
        saved = self.db.execute("SELECT artifact FROM models WHERE id=1").fetchone()
        self.model: dict[str, Any] | None = json.loads(saved[0]) if saved else None

    def receive(self, frame: Frame) -> None:
        at = frame.observed_at.replace(minute=0, second=0, microsecond=0).isoformat()
        if at == self.last_hour:
            return
        self.last_hour = at
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO observations VALUES (?, ?, ?, ?)",
                (
                    at,
                    sum(b.occupant is not None for b in frame.beds),
                    sum(p.status == "waiting" for p in frame.patients),
                    sum(
                        b.opened and b.hygiene == "ready" and not b.occupant and not b.reserved_for
                        for b in frame.beds
                    ),
                ),
            )

    @staticmethod
    def features(row: tuple[Any, ...]) -> list[float]:
        hour = datetime.fromisoformat(row[0]).astimezone(PARIS).hour
        return [
            1,
            float(row[1]),
            float(row[2]),
            math.sin(hour * math.pi / 12),
            math.cos(hour * math.pi / 12),
        ]

    def fit(self) -> None:
        if self.model is not None:
            return
        rows = self.db.execute("SELECT * FROM observations ORDER BY at").fetchall()
        if len(rows) < 24 * 14:
            raise ValueError("insufficient_observed_training_history")
        # Exclude startup transients; last seven full days remain unseen by fitting.
        rows = rows[24:]
        x = np.array([self.features(r) for r in rows[:-1]])
        y = np.array([r[1] for r in rows[1:]], dtype=float)
        split = len(y) - 7 * 24
        penalty = np.eye(x.shape[1])
        penalty[0, 0] = 0
        coefficients = np.linalg.solve(x[:split].T @ x[:split] + penalty, x[:split].T @ y[:split])
        predictions = np.clip(x[split:] @ coefficients, 0, self.capacity)
        mae = float(np.mean(np.abs(predictions - y[split:])))
        baseline = float(np.mean(np.abs(x[split:, 1] - y[split:])))
        self.model = {
            "version": "occupancy-ridge-hourly-v1",
            "synthetic": True,
            "features": ["intercept", "occupied", "waiting", "paris_hour_sin", "paris_hour_cos"],
            "coefficients": coefficients.tolist(),
            "horizon_minutes": 60,
            "train_from": rows[0][0],
            "train_until": rows[split][0],
            "validation_from": rows[split + 1][0],
            "validation_until": rows[-1][0],
            "training_pairs": split,
            "validation_pairs": len(y) - split,
            "mae_beds": round(mae, 4),
            "persistence_mae_beds": round(baseline, 4),
            "selected": "ridge" if mae < baseline else "persistence",
            "data_sha256": hashlib.sha256(
                json.dumps(rows, separators=(",", ":")).encode()
            ).hexdigest(),
        }
        with self.db:
            self.db.execute("INSERT INTO models VALUES (1, ?)", (json.dumps(self.model),))

    def summary(self) -> dict[str, Any]:
        rows = self.db.execute("SELECT * FROM observations ORDER BY at").fetchall()
        latest = rows[-1]
        assert self.model is not None
        prediction = float(latest[1])
        if self.model["selected"] == "ridge":
            prediction = float(np.dot(self.features(latest), self.model["coefficients"]))
        daily: dict[str, list[int]] = {}
        for row in rows:
            day = datetime.fromisoformat(row[0]).astimezone(PARIS).date().isoformat()
            daily.setdefault(day, []).append(row[1])
        return {
            "source": "synthetic_observed_exports",
            "from": rows[0][0],
            "until": latest[0],
            "samples": len(rows),
            "capacity": self.capacity,
            "daily": [
                {
                    "date": day,
                    "mean_occupied": round(sum(values) / len(values), 2),
                    "samples": len(values),
                }
                for day, values in daily.items()
            ],
            "recent": [
                {"at": r[0], "occupied": r[1], "waiting": r[2], "ready": r[3]} for r in rows[-48:]
            ],
            "model": self.model,
            "forecast": {
                "origin": latest[0],
                "horizon_minutes": 60,
                "occupied": round(max(0, min(self.capacity, prediction)), 1),
            },
        }

    def export_rows(self) -> list[dict[str, Any]]:
        return [
            {"at": row[0], "occupied": row[1], "waiting": row[2], "ready": row[3]}
            for row in self.db.execute("SELECT * FROM observations ORDER BY at")
        ]

    def close(self) -> None:
        self.db.close()
