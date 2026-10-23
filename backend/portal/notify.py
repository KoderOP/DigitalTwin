"""Patient notification service: priorities, frequency caps, safety bypass, escalation.

Priority 0  safety: low glucose (detected or predicted) and RED spike alerts. **Always delivered**:
            they cannot be disabled and are not capped, only de-duplicated per episode.
Priority 1  doctor messages
Priority 2  AMBER "heads-up" (capped: ``daily_cap`` per simulated day, ``min_gap_min`` apart)
Priority 3  medication / care-plan reminders (once per configured time)

Text is stored as i18n keys + parameters and rendered in the patient's current language at view time.
"""
from __future__ import annotations

import json

import pandas as pd

from backend.portal.explain_text import is_low, low_predicted
from backend.portal.i18n import t
from backend.portal.store import PortalStore

SAFETY_DEDUPE_MIN = 60
HYPO_DEDUPE_MIN = 30


class Notifier:
    def __init__(self, store: PortalStore) -> None:
        self.store = store
        self.prev_level: dict[str, str] = {}

    # ------------------------------------------------------------------------------------------
    def _recent(self, pid: str, kind: str, since: pd.Timestamp) -> bool:
        r = self.store.q("SELECT 1 FROM notifications WHERE pid=? AND kind=? AND delivered=1 AND ts_sim>=? LIMIT 1",
                         (pid, kind, since.isoformat()))
        return bool(r)

    def emit(self, pid: str, now: pd.Timestamp, kind: str, priority: int, safety: bool, level: str,
             title_key: str, body_key: str, params: dict, confidence: float | None, cfg: dict) -> dict:
        """Insert a notification, applying caps to non-safety priorities. Returns the stored row."""
        suppressed = None
        if not safety and priority == 2:
            day0 = now.normalize().isoformat()
            n_today = self.store.q("SELECT COUNT(*) AS n FROM notifications WHERE pid=? AND safety=0 AND priority=2 "
                                   "AND delivered=1 AND ts_sim>=?", (pid, day0))[0]["n"]
            gap_since = (now - pd.Timedelta(minutes=cfg["alerts"]["min_gap_min"])).isoformat()
            last = self.store.q("SELECT COUNT(*) AS n FROM notifications WHERE pid=? AND safety=0 AND priority=2 "
                                "AND delivered=1 AND ts_sim>=?", (pid, gap_since))[0]["n"]
            if n_today >= cfg["alerts"]["daily_cap"]:
                suppressed = "daily_cap"
            elif last:
                suppressed = "min_gap"
        nid = self.store.x(
            "INSERT INTO notifications (pid, ts_sim, kind, priority, safety, level, title, body, confidence, delivered, suppressed) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (pid, now.isoformat(), kind, priority, int(safety), level, title_key,
             json.dumps({"key": body_key, "params": params}), confidence, int(suppressed is None), suppressed))
        return {"id": nid, "kind": kind, "delivered": suppressed is None, "suppressed": suppressed, "safety": safety}

    # ------------------------------------------------------------------------------------------
    def process(self, pid: str, now: pd.Timestamp, pred: dict | None, cgm: float | None, cfg: dict) -> list[dict]:
        """Evaluate one tick for one ACTIVE patient; return newly created notifications."""
        out: list[dict] = []
        if pred is None:
            return out
        # --- safety: low glucose (always on) ---
        if is_low(cgm, pred):
            if not self._recent(pid, "hypo_detected", now - pd.Timedelta(minutes=HYPO_DEDUPE_MIN)):
                out.append(self.emit(pid, now, "hypo_detected", 0, True, "LOW", "notify.hypo_title", "notify.hypo_detected",
                                     {"value": int(cgm)}, None, cfg))
        elif low_predicted(pred) and not self._recent(pid, "hypo_predicted", now - pd.Timedelta(minutes=SAFETY_DEDUPE_MIN)):
            out.append(self.emit(pid, now, "hypo_predicted", 0, True, "LOW", "notify.hypo_title", "notify.hypo_predicted",
                                 {}, pred.get("hypo_risk"), cfg))
        level = pred["level"]
        mins = pred.get("minutes_to_spike")
        # personal watch zone: the doctor's AMBER threshold (RED stays at the validated model threshold)
        watch = pred["eligible"] and pred["risk"] >= cfg["alerts"]["amber_threshold"]
        was_watch = self.prev_level.get(pid) == "WATCH"
        # --- safety: RED (always on) ---
        if level == "RED" and not self._recent(pid, "red", now - pd.Timedelta(minutes=SAFETY_DEDUPE_MIN)):
            out.append(self.emit(pid, now, "red", 0, True, "RED", "notify.red_title",
                                 "status.RED" if mins else "status.RED_nominutes", {"minutes": mins}, pred["risk"], cfg))
        # --- AMBER heads-up (capped), only when entering the watch zone ---
        elif watch and not was_watch and level != "RED":
            out.append(self.emit(pid, now, "amber", 2, False, "AMBER", "notify.amber_title",
                                 "status.AMBER" if mins else "status.AMBER_nominutes", {"minutes": mins}, pred["risk"], cfg))
        self.prev_level[pid] = "WATCH" if (watch or level == "RED") else "CLEAR"
        # --- medication reminders (reminders only; never dose changes) ---
        for r in cfg["care_plan"].get("medication_reminders", []):
            hh, mm = (int(x) for x in r["time"].split(":"))
            due = now.normalize() + pd.Timedelta(hours=hh, minutes=mm)
            if pd.Timedelta(0) <= now - due < pd.Timedelta(minutes=5):
                out.append(self.emit(pid, now, "reminder", 3, False, "INFO", "notify.reminder_title", "actions.med_reminder",
                                     {"label": r["label"]}, None, cfg))
        return out

    def escalate(self, pid: str, now: pd.Timestamp, cfg: dict, doctor_name: str) -> list[dict]:
        """Unacknowledged safety alerts older than ``escalate_after_min`` go to the escalation contacts (mock)."""
        cutoff = (now - pd.Timedelta(minutes=cfg["alerts"]["escalate_after_min"])).isoformat()
        rows = self.store.q("SELECT id, kind, ts_sim FROM notifications WHERE pid=? AND safety=1 AND delivered=1 "
                            "AND seen_at IS NULL AND escalated=0 AND ts_sim<=?", (pid, cutoff))
        out = []
        for r in rows:
            body = (f"[Demo escalation] Patient {pid}: safety alert '{r['kind']}' at {r['ts_sim'][11:16]} not acknowledged "
                    f"within {cfg['alerts']['escalate_after_min']} min. Synthetic demo, not a real person.")
            for c in cfg["alerts"].get("escalation_contacts", []):
                self.store.send(pid, c["channel"], f"{c['name']} ({c['relation']}) {c['handle']}", body)
            self.store.send(pid, "dashboard", doctor_name, body)
            self.store.x("UPDATE notifications SET escalated=1 WHERE id=?", (r["id"],))
            out.append({"id": r["id"], "kind": r["kind"]})
        return out

    # ------------------------------------------------------------------------------------------
    def render(self, row: dict, lang: str, doctor: str) -> dict:
        body = json.loads(row["body"])
        p = {**body.get("params", {}), "doctor": doctor}
        if "food_key" in p:  # localise the food name at view time
            from backend.portal.food_insights import food_label

            p["food"] = food_label(p["food_key"], p.get("food"), lang)
        title = t(lang, row["title"], **p)
        text = t(lang, body["key"], **p)
        conf = row["confidence"]
        return {
            "id": row["id"], "ts": row["ts_sim"], "kind": row["kind"], "priority": row["priority"], "safety": bool(row["safety"]),
            "level": row["level"], "title": title, "body": text,
            "confidence": None if conf is None else {"pct": round(conf * 100),
                                                     "label": t(lang, "confidence." + ("high" if max(conf, 1 - conf) >= 0.8 else "medium" if max(conf, 1 - conf) >= 0.6 else "low"))},
            "seen": row["seen_at"] is not None, "understood": row["understood"],
            "disclaimer": t(lang, "notify.disclaimer"),
            "first_aid": t(lang, "first_aid") if row["kind"].startswith("hypo") else None,
        }
