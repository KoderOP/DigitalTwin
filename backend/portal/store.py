"""SQLite persistence for the patient interface (same database and lock as the audit trail).

Data minimisation: the store keeps pseudonymous IDs, configuration, hashed OTPs and device ids,
in-app messages and patient logs. It holds no names, phone numbers or real identifiers. Escalation
contacts are fictional demo entries.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from backend.audit import AuditLog

SCHEMA = """
CREATE TABLE IF NOT EXISTS portal_patient (
    pid TEXT PRIMARY KEY, doctor_id TEXT NOT NULL, state TEXT NOT NULL, config TEXT,
    session_id TEXT, device_hash TEXT, consent TEXT, created TEXT, updated TEXT, last_activity TEXT
);
CREATE TABLE IF NOT EXISTS invites (
    jti TEXT PRIMARY KEY, pid TEXT NOT NULL, created TEXT, expires_ts REAL, status TEXT,
    otp_hash TEXT, otp_expires_ts REAL, attempts INTEGER DEFAULT 0, sends INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, pid TEXT, channel TEXT, recipient TEXT, body TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, pid TEXT, ts_sim TEXT, sender TEXT, author TEXT, body TEXT, read_at TEXT
);
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT, pid TEXT, ts_sim TEXT, source TEXT, kind TEXT, title TEXT, body TEXT,
    status TEXT DEFAULT 'open', done_at TEXT
);
CREATE TABLE IF NOT EXISTS patient_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, pid TEXT, ts_sim TEXT, kind TEXT, payload TEXT, duration_ms INTEGER
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT, pid TEXT, ts_sim TEXT, kind TEXT, priority INTEGER, safety INTEGER,
    level TEXT, title TEXT, body TEXT, confidence REAL, delivered INTEGER, suppressed TEXT,
    seen_at TEXT, understood INTEGER, escalated INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS caregiver_links (
    jti TEXT PRIMARY KEY, pid TEXT, created TEXT, revoked INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS extra_patients (
    pid TEXT PRIMARY KEY, doctor_id TEXT, ehr TEXT, latent TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PortalStore:
    def __init__(self, audit: AuditLog) -> None:
        self.audit = audit
        self._c = audit._conn
        self._lock = audit._lock
        with self._lock:
            self._c.executescript(SCHEMA)
            self._c.commit()

    # -- generic helpers ---------------------------------------------------------------------
    def q(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            cur = self._c.execute(sql, args)
            cols = [d[0] for d in cur.description] if cur.description else []
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def x(self, sql: str, args: tuple = ()) -> int:
        with self._lock:
            cur = self._c.execute(sql, args)
            self._c.commit()
            return cur.lastrowid

    # -- patients ------------------------------------------------------------------------------
    def patient(self, pid: str) -> dict | None:
        r = self.q("SELECT * FROM portal_patient WHERE pid=?", (pid,))
        if not r:
            return None
        r = r[0]
        r["config"] = json.loads(r["config"]) if r["config"] else None
        r["consent"] = json.loads(r["consent"]) if r["consent"] else None
        return r

    def ensure_patient(self, pid: str, doctor_id: str) -> None:
        self.x("INSERT OR IGNORE INTO portal_patient (pid, doctor_id, state, created, updated) VALUES (?,?,?,?,?)",
               (pid, doctor_id, "NOT_ENROLLED", now_iso(), now_iso()))

    def update_patient(self, pid: str, **fields: Any) -> None:
        if not fields:
            return
        fields = {k: (json.dumps(v) if k in ("config", "consent") and v is not None else v) for k, v in fields.items()}
        fields["updated"] = now_iso()
        sets = ", ".join(f"{k}=?" for k in fields)
        self.x(f"UPDATE portal_patient SET {sets} WHERE pid=?", tuple(fields.values()) + (pid,))

    def all_patients(self) -> list[dict]:
        return self.q("SELECT pid, doctor_id, state, last_activity, updated FROM portal_patient")

    # -- outbox (mock SMS / email) -------------------------------------------------------------
    def send(self, pid: str, channel: str, recipient: str, body: str) -> int:
        return self.x("INSERT INTO outbox (ts, pid, channel, recipient, body) VALUES (?,?,?,?,?)", (now_iso(), pid, channel, recipient, body))

    def outbox(self, limit: int = 30, pid: str | None = None) -> list[dict]:
        if pid:
            return self.q("SELECT * FROM outbox WHERE pid=? ORDER BY id DESC LIMIT ?", (pid, limit))
        return self.q("SELECT * FROM outbox ORDER BY id DESC LIMIT ?", (limit,))
