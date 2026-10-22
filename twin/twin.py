"""DigitalTwin: one virtual patient's live state, predictions, alerts and what-if simulator."""
from __future__ import annotations

import itertools
from collections import deque

import numpy as np
import pandas as pd

from common.glycemic import agp_profile, spike_onsets, summary_metrics
from ml.features import EVENT_CHANNEL, FRAME_COLUMNS
from twin.predictor import Predictor
from twin.simulator import PersonalizedSimulator
from twin.whatif import run_what_if

DEVICE_FIELDS = ("cgm", "hr", "hrv_rmssd", "steps", "activity", "sleep_stage", "spo2", "skin_temp")
RECALIBRATE_EVERY_MIN = 6 * 60
_alert_ids = itertools.count(1)


def _nan(x) -> float:
    return float("nan") if x is None else float(x)


def _clean(v):
    if v is None:
        return None
    if isinstance(v, (float, np.floating)):
        return None if np.isnan(v) else round(float(v), 2)
    if isinstance(v, (np.integer,)):
        return int(v)
    return v


class DigitalTwin:
    """Holds the static EHR profile, a rolling window of live wearable data and a personalised simulator."""

    def __init__(self, pid: str, ehr_raw: dict, ehr_encoded: pd.Series, predictor: Predictor,
                 buffer_rows: int = 600, agp_rows: int = 14 * 288) -> None:
        self.pid = pid
        self.ehr = ehr_raw
        self.ehr_encoded = ehr_encoded
        self.predictor = predictor
        self.rows: deque[dict] = deque(maxlen=buffer_rows)  # ~50 h of 5-min rows (features need 48 h)
        self.cgm_hist: deque[tuple[pd.Timestamp, float]] = deque(maxlen=agp_rows)
        self.events: deque[dict] = deque(maxlen=400)
        self.pred_hist: deque[dict] = deque(maxlen=288)
        self.sim = PersonalizedSimulator(pd.Series(ehr_raw))
        self.prediction: dict | None = None
        self.alerts: list[dict] = []
        self.notes: list[dict] = []
        self._last_cal: pd.Timestamp | None = None
        self._last_alert_ts: pd.Timestamp | None = None
        self.last_sleep_h: float | None = None

    # ------------------------------------------------------------------------------------------
    # ingestion (online state update)
    # ------------------------------------------------------------------------------------------
    def ingest_history(self, ts: pd.Timestamp, cgm: float) -> None:
        """Long-term CGM history only (used for the AGP); no state update."""
        self.cgm_hist.append((ts, cgm))

    def ingest(self, rec: dict, events: list[dict] | None = None) -> None:
        """Ingest one 5-min device record (+ logged events in that interval) and update the twin."""
        ts = pd.Timestamp(rec["ts"])
        row = {"ts": ts, **{k: _nan(rec.get(k)) for k in DEVICE_FIELDS}}
        row["sleep_stage"] = 0 if np.isnan(row["sleep_stage"]) else int(row["sleep_stage"])
        for c in ("carbs", "med_met", "med_su", "med_dpp4", "med_sglt2", "ins_units"):
            row[c] = 0.0
        for e in events or []:
            if e.get("type") == "meal":
                row["carbs"] += float(e.get("logged_amount", 0))
            elif e.get("name") in EVENT_CHANNEL:
                row[EVENT_CHANNEL[e["name"]]] += float(e.get("logged_amount", 0))
            self.events.append({"ts": pd.Timestamp(e["ts"]).isoformat(), "type": e.get("type"), "name": e.get("name"),
                                "label": e.get("label"), "amount": _clean(e.get("logged_amount")), "injected": bool(e.get("injected", False))})
        woke = bool(self.rows) and self.rows[-1]["sleep_stage"] > 0 and row["sleep_stage"] == 0 and 5 <= ts.hour <= 11
        self.rows.append(row)
        self.cgm_hist.append((ts, row["cgm"]))
        if woke:
            recent = list(self.rows)[-144:]
            self.last_sleep_h = sum(r["sleep_stage"] > 0 for r in recent) * 5 / 60
        self.sim.sync(row, ts.hour * 60 + ts.minute, self.last_sleep_h if woke else None)
        if len(self.rows) >= 288 and (self._last_cal is None or (ts - self._last_cal).total_seconds() >= RECALIBRATE_EVERY_MIN * 60):
            self.sim.calibrate(self.frame(), self.last_sleep_h or 7.0)
            self._last_cal = ts
        self._update_alert_outcomes()

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(list(self.rows), columns=FRAME_COLUMNS)

    @property
    def now(self) -> pd.Timestamp | None:
        return self.rows[-1]["ts"] if self.rows else None

    # ------------------------------------------------------------------------------------------
    # prediction + alerts
    # ------------------------------------------------------------------------------------------
    def update_prediction(self, explain: bool = False) -> dict:
        p = self.predictor.predict(self.frame(), self.ehr_encoded, self.ehr, explain=explain)
        p["ts"] = self.now.isoformat()
        p["nocturnal_flag"] = self._nocturnal(p)
        if not explain and self.prediction and "explanation" in self.prediction:
            p["explanation"] = self.prediction["explanation"]
            p["explanation_stale"] = True
        self.prediction = p
        self.pred_hist.append({"ts": p["ts"], "risk": p["risk"] if p["eligible"] else None, "level": p["level"],
                               "p50_60": p["forecast"][1]["p50"], "p10_60": p["forecast"][1]["p10"], "p90_60": p["forecast"][1]["p90"]})
        self._maybe_alert(p)
        return p

    def backfill_predictions(self, hours: int = 12) -> None:
        """Fill the risk history for the last ``hours`` in one batched call (startup only, no alerts)."""
        self.pred_hist.clear()
        self.pred_hist.extend(self.predictor.predict_many(self.frame(), self.ehr_encoded, hours * 12))

    def _nocturnal(self, p: dict) -> str | None:
        h = self.now.hour
        if not (h >= 22 or h < 6):
            return None
        if (p.get("hypo_risk") or 0) >= 0.2 or min(f["p10"] for f in p["forecast"]) < 70:
            return "Nocturnal hypoglycemia risk"
        if p["forecast"][-1]["p50"] > 180:
            return "Nocturnal hyperglycemia expected"
        return None

    def _maybe_alert(self, p: dict) -> None:
        """Raise a clinician alert at the notification level (RED by default; AMBER stays a visual watch level)."""
        notify = ("AMBER", "RED") if self.predictor.notify_level == "AMBER" else ("RED",)
        if p["level"] not in notify:
            return
        refr = pd.Timedelta(minutes=self.predictor.refractory_min)
        if self._last_alert_ts is not None and self.now - self._last_alert_ts < refr:
            active = [a for a in self.alerts if a["status"] == "active"]
            if active and p["level"] == "RED" and active[-1]["level"] == "AMBER":
                active[-1].update(level="RED", risk=p["risk"], escalated_at=p["ts"])  # escalate in place
            return
        self._last_alert_ts = self.now
        self.alerts.append({
            "id": next(_alert_ids), "patient_id": self.pid, "ts": p["ts"], "level": p["level"], "risk": p["risk"],
            "minutes_to_spike": p["minutes_to_spike"], "status": "active", "outcome": "pending",
            "g_at_alert": p["g_now"], "top_factors": [f["title"] for f in p.get("explanation", [])[:3]],
        })

    def _update_alert_outcomes(self) -> None:
        """Mark pending alerts as 'spike occurred' (with lead time) or 'no spike' after 120 min (an honest track record)."""
        pending = [a for a in self.alerts if a["outcome"] == "pending"]
        if not pending:
            return
        tail = list(self.rows)[-40:]
        g = np.array([r["cgm"] for r in tail])
        on = spike_onsets(g)
        onset_ts = [tail[i]["ts"] for i in np.flatnonzero(on)]
        for a in pending:
            t0 = pd.Timestamp(a["ts"])
            hit = [t for t in onset_ts if t0 < t <= t0 + pd.Timedelta(minutes=120)]
            if hit:
                a["outcome"] = "spike_occurred"
                a["lead_min"] = int((hit[0] - t0).total_seconds() // 60)
            elif self.now > t0 + pd.Timedelta(minutes=120):
                a["outcome"] = "no_spike"

    def acknowledge(self, alert_id: int, user: str) -> dict | None:
        for a in self.alerts:
            if a["id"] == alert_id:
                a.update(status="acknowledged", acknowledged_by=user, acknowledged_at=self.now.isoformat())
                return a
        return None

    # ------------------------------------------------------------------------------------------
    def what_if(self, scenarios: list[dict], horizon_min: int | None = None) -> dict:
        return run_what_if(self.sim, self.now, scenarios, horizon_min)

    # ------------------------------------------------------------------------------------------
    # views
    # ------------------------------------------------------------------------------------------
    def data_quality(self) -> dict:
        rows = list(self.rows)
        last12 = rows[-12:]
        last288 = rows[-288:]
        cgm_ok_1h = np.mean([not np.isnan(r["cgm"]) for r in last12]) if last12 else 0
        cgm_ok_24h = np.mean([not np.isnan(r["cgm"]) for r in last288]) if last288 else 0
        wear_ok_1h = np.mean([not np.isnan(r["hr"]) for r in last12]) if last12 else 0
        since = next((k * 5 for k, r in enumerate(reversed(rows)) if not np.isnan(r["cgm"])), None)
        status = "good" if cgm_ok_1h >= 0.9 and (since or 0) <= 10 else ("degraded" if cgm_ok_1h >= 0.5 else "poor")
        return {"cgm_coverage_1h": round(float(cgm_ok_1h), 2), "cgm_coverage_24h": round(float(cgm_ok_24h), 2),
                "wearable_coverage_1h": round(float(wear_ok_1h), 2), "minutes_since_cgm": since, "status": status,
                "imputing": bool(since is not None and since > 0)}

    def header(self) -> dict:
        e = self.ehr
        meds = []
        if e.get("metformin_mg"):
            meds.append(f"Metformin {e['metformin_mg']} mg/day")
        if e.get("sulfonylurea_mg"):
            meds.append(f"Glimepiride {e['sulfonylurea_mg']} mg/day")
        if e.get("dpp4"):
            meds.append("Teneligliptin 20 mg (DPP-4i)")
        if e.get("sglt2"):
            meds.append("Dapagliflozin 10 mg (SGLT2i)")
        if e.get("insulin_type") and e["insulin_type"] != "none":
            meds.append(f"{'Premix 30/70' if e['insulin_type'] == 'premix_30_70' else 'Glargine'} {e['insulin_units_day']} U/day")
        comorb = [n for k, n in (("hypertension", "Hypertension"), ("dyslipidemia", "Dyslipidemia"), ("prior_cvd", "Prior CVD")) if e.get(k)]
        if int(e.get("ckd_stage", 1)) >= 3:
            comorb.append(f"CKD stage {int(e['ckd_stage'])}")
        return {
            "patient_id": self.pid, "age": int(e["age"]), "sex": e["sex"], "region": e["region"],
            "years_since_dx": float(e["years_since_dx"]), "hba1c": float(e["hba1c"]), "bmi": float(e["bmi"]),
            "bmi_band_sa": e["bmi_band_sa"], "waist_cm": float(e["waist_cm"]), "egfr": float(e["egfr"]),
            "diet": e["diet"], "staple": e["staple"], "early_onset": bool(e["early_onset"]), "prs": float(e["prs"]),
            "medications": meds, "comorbidities": comorb, "fasting_glucose": float(e["fasting_glucose"]),
            "ldl": float(e["ldl"]), "triglycerides": float(e["triglycerides"]),
        }

    def summary(self) -> dict:
        p = self.prediction or {}
        f = p.get("features", {})
        slope = f.get("w_slope_15m") or 0
        trend = "up_fast" if slope > 2 else "up" if slope > 1 else "down_fast" if slope < -2 else "down" if slope < -1 else "flat"
        last = self.rows[-1] if self.rows else {}
        return {
            "patient_id": self.pid, "age": int(self.ehr["age"]), "sex": self.ehr["sex"], "region": self.ehr["region"],
            "hba1c": float(self.ehr["hba1c"]), "bmi_band_sa": self.ehr["bmi_band_sa"],
            "insulin": self.ehr.get("insulin_type", "none") != "none",
            "cgm": _clean(last.get("cgm")), "g_now": p.get("g_now"), "trend": trend, "risk": p.get("risk"),
            "level": p.get("level", "GREEN"), "minutes_to_spike": p.get("minutes_to_spike"),
            "nocturnal_flag": p.get("nocturnal_flag"), "hypo_risk": p.get("hypo_risk"),
            "active_alerts": sum(a["status"] == "active" for a in self.alerts),
            "data_quality": self.data_quality()["status"], "ts": p.get("ts"),
        }

    def detail(self, hours: int = 12) -> dict:
        rows = list(self.rows)[-hours * 12:]
        series = [{"ts": r["ts"].isoformat(), **{k: _clean(r[k]) for k in ("cgm", "hr", "hrv_rmssd", "steps", "activity", "sleep_stage", "spo2")}}
                  for r in rows]
        start = rows[0]["ts"] if rows else None
        events = [e for e in self.events if start is None or pd.Timestamp(e["ts"]) >= start]
        hist = list(self.cgm_hist)
        h_ts = pd.Series([t for t, _ in hist])
        h_g = pd.Series([g for _, g in hist], dtype=float)
        last24 = h_g.tail(288)
        daily = []
        if len(hist):
            dfh = pd.DataFrame({"ts": h_ts, "g": h_g})
            for d, grp in dfh.groupby(dfh.ts.dt.date):
                mtr = summary_metrics(grp.g)
                daily.append({"date": str(d), "tir": mtr["tir"], "tar": mtr["tar"], "tbr": mtr["tbr"], "mean": mtr["mean"], "cv": mtr["cv"]})
        return {
            "header": self.header(), "summary": self.summary(), "series": series, "events": events,
            "prediction": self.prediction, "prediction_history": list(self.pred_hist)[-hours * 12:],
            "metrics_24h": summary_metrics(last24), "metrics_14d": summary_metrics(h_g),
            "agp": agp_profile(h_ts, h_g), "daily": daily[-14:], "data_quality": self.data_quality(),
            "alerts": self.alerts[-20:][::-1], "notes": self.notes[-20:][::-1], "simulator": self.sim.describe(),
            "last_sleep_h": None if self.last_sleep_h is None else round(self.last_sleep_h, 1),
        }
