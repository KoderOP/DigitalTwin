"""SQLite audit trail and simulated consent registry (DPDP Act / HIPAA-style accountability).

Every clinician action (view, acknowledge, note, intervention, what-if) and every demo-control action
is appended with wall-clock time, simulated time, pseudonymous actor and patient ID. No real
identifiers are ever stored.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_wall TEXT NOT NULL,
    ts_sim TEXT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    patient_id TEXT,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS consent (
    patient_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    scope TEXT NOT NULL,
    granted_at TEXT NOT NULL,
    note TEXT
);
"""


class AuditLog:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._lock = threading.Lock()

    def log(self, actor: str, action: str, patient_id: str | None = None, detail: dict | None = None,
            ts_sim: str | None = None) -> dict:
        row = {"ts_wall": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ts_sim": ts_sim, "actor": actor,
               "action": action, "patient_id": patient_id, "detail": json.dumps(detail or {}, default=str)}
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO audit (ts_wall, ts_sim, actor, action, patient_id, detail) VALUES (?,?,?,?,?,?)",
                (row["ts_wall"], row["ts_sim"], actor, action, patient_id, row["detail"]))
            self._conn.commit()
            row["id"] = cur.lastrowid
        return row

    def recent(self, limit: int = 100, patient_id: str | None = None) -> list[dict]:
        q = "SELECT id, ts_wall, ts_sim, actor, action, patient_id, detail FROM audit"
        args: tuple = ()
        if patient_id:
            q += " WHERE patient_id = ?"
            args = (patient_id,)
        q += " ORDER BY id DESC LIMIT ?"
        with self._lock:
            rows = self._conn.execute(q, args + (limit,)).fetchall()
        keys = ("id", "ts_wall", "ts_sim", "actor", "action", "patient_id", "detail")
        return [{**dict(zip(keys, r)), "detail": json.loads(r[6] or "{}")} for r in rows]

    def seed_consent(self, patient_ids: list[str], consented: dict[str, bool]) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock:
            for pid in patient_ids:
                self._conn.execute(
                    "INSERT OR IGNORE INTO consent (patient_id, status, scope, granted_at, note) VALUES (?,?,?,?,?)",
                    (pid, "granted" if consented.get(pid, False) else "withdrawn", "twin_monitoring+clinician_view",
                     now, "SIMULATED consent record for a synthetic patient"))
            self._conn.commit()

    def consent(self, patient_id: str) -> dict | None:
        with self._lock:
            r = self._conn.execute("SELECT patient_id, status, scope, granted_at, note FROM consent WHERE patient_id = ?",
                                   (patient_id,)).fetchone()
        return dict(zip(("patient_id", "status", "scope", "granted_at", "note"), r)) if r else None
