"""Live simulation engine: virtual-patient world -> stream ingestion -> twins -> predictions.

Two stream modes:
* ``internal`` (default, single command demo): the world simulator runs inside the backend process
  and pushes each 5-min record through the same :meth:`Engine.ingest` path an external device
  gateway would use.
* ``external``: no in-process world; records arrive via ``POST /api/ingest``
  (see ``backend/stream_client.py``).
"""
from __future__ import annotations

import json
import threading
import time
import zlib
from typing import Callable

import numpy as np
import pandas as pd

from backend.audit import AuditLog
from common import get_config, get_logger, path_of
from data_gen.ehr_generator import ehr_feature_matrix
from data_gen.physiology import PhysioParams
from data_gen.world import Event, World
from twin.predictor import Predictor
from twin.twin import DEVICE_FIELDS, DigitalTwin

log = get_logger("backend.engine")
SPEEDS = (1, 10, 60, 300, 900)
INJECTIONS = {
    "heavy_meal": "Heavy carb meal (~120 g, high GI)",
    "missed_medication": "Missed medication (next 24 h)",
    "poor_sleep": "Poor-sleep night (tonight ~4 h, fragmented)",
    "sensor_dropout": "CGM sensor dropout (60 min)",
    "exercise": "Brisk walk (30 min)",
    "stress": "Acute stress episode (2 h)",
}


class Engine:
    def __init__(self, n_patients: int | None = None, warmup_days: int = 14, start_clock: str = "17:30",
                 mode: str = "internal") -> None:
        cfg = get_config()
        self.cfg = cfg
        self.mode = mode
        self.lock = threading.RLock()
        data_dir, art = path_of("data_dir"), path_of("artifacts_dir")
        self.patients = pd.read_csv(data_dir / "ehr" / "patients.csv", index_col="patient_id")
        self.latent = pd.read_csv(data_dir / "ehr" / "latent_truth.csv", index_col="patient_id")
        self.ehr_encoded = ehr_feature_matrix(self.patients)
        splits = json.loads((art / "splits.json").read_text())
        n = n_patients or cfg["serving"]["demo_patients"]
        # demo patients come from the held-out TEST split: the models never saw them
        self.ids = sorted(splits["test"])[:n]
        self.predictor = Predictor()
        self.audit = AuditLog(path_of("db_path"))
        self.audit.seed_consent(self.ids, self.patients["consent_twin_monitoring"].astype(bool).to_dict())
        self.manifest = json.loads((data_dir / "manifest.json").read_text())
        self.speed = cfg["serving"]["default_speed"]
        self.paused = False
        self.warmup_days = warmup_days
        self.start_clock = start_clock
        self.focus: dict[int, str] = {}  # websocket id -> focused patient id
        self.post_tick_hooks: list[Callable[[], None]] = []  # e.g. the patient-portal notification service
        self.tick_ms = 0.0
        self.base_ids = list(self.ids)
        self.extra: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}  # patients created at runtime (EHR, latent)
        self.reset()

    # ------------------------------------------------------------------------------------------
    def reset(self) -> None:
        with self.lock:
            t0 = time.time()
            self.ids = list(self.base_ids)
            pats = self.patients.loc[self.ids]
            lat = self.latent.loc[self.ids]
            params = PhysioParams.from_frame(lat)
            start = pd.Timestamp(self.cfg["cohort"]["start_date"])
            self.world = World(pats, lat, params, start, seed=self.cfg["seed"] + 99, sensor_cfg=self.cfg["simulation"]["sensor"],
                               start_day=self.cfg["cohort"]["n_days"])
            self.worlds = [self.world]
            self.where: dict[str, tuple[World, int]] = {pid: (self.world, i) for i, pid in enumerate(self.ids)}
            self.twins = {pid: DigitalTwin(pid, self._ehr_raw(pid), self.ehr_encoded.loc[pid], self.predictor) for pid in self.ids}
            hh, mm = (int(x) for x in self.start_clock.split(":"))
            n_blocks = (self.warmup_days * 1440 + hh * 60 + mm) // 5
            self._warm(self.world, self.ids, n_blocks)
            for pid in list(self.extra):
                self._build_extra(pid)
            self.audit.log("system", "engine_reset", detail={"patients": len(self.ids), "clock": self.clock()}, ts_sim=self.clock())
            log.info("Engine ready: %d twins, clock %s (%.1fs)", len(self.ids), self.clock(), time.time() - t0)

    def _warm(self, world: World, ids: list[str], n_blocks: int) -> None:
        """Advance a world through warm-up, filling twin history; calibrate and back-fill predictions."""
        full_from = n_blocks - 2 * 288 - 24  # last ~50 h fully ingested (feature window)
        for k in range(n_blocks):
            rec, evs = world.advance_block()
            if k < full_from:
                ts = world.now()
                by_pid = self._events_by_patient(world, evs)
                for i, pid in enumerate(ids):
                    self.twins[pid].ingest_history(ts, float(rec["cgm"][i]), by_pid.get(i))
            else:
                self._ingest_block(rec, evs, calibrate=False, world=world, ids=ids)
        for pid in ids:
            tw = self.twins[pid]
            tw.sim.calibrate(tw.frame(), tw.last_sleep_h or 7.0)
            tw._last_cal = tw.now
            tw.backfill_predictions(12)
            tw.pred_hist.pop()  # the live prediction below replaces the last back-filled point
            tw.update_prediction(explain=True)

    # ------------------------------------------------------------------------------------------
    # runtime patients (doctor "creates a new synthetic patient")
    # ------------------------------------------------------------------------------------------
    def add_patient(self, ehr: pd.DataFrame, latent: pd.DataFrame) -> str:
        """Add a freshly generated synthetic patient: own world on the shared clock, 3 days of warm-up."""
        pid = str(ehr.index[0])
        with self.lock:
            self.extra[pid] = (ehr, latent)
            self._build_extra(pid)
        return pid

    def _build_extra(self, pid: str) -> None:
        ehr, latent = self.extra[pid]
        if pid not in self.patients.index:
            self.patients = pd.concat([self.patients, ehr.reindex(columns=self.patients.columns)])
            self.ehr_encoded = pd.concat([self.ehr_encoded, ehr_feature_matrix(ehr)[self.ehr_encoded.columns]])
        params = PhysioParams.from_frame(latent)
        main = self.world
        start_day = main.minute // 1440 - 3
        w = World(ehr, latent, params, main.start, seed=zlib.crc32(pid.encode()) % 10**6, sensor_cfg=self.cfg["simulation"]["sensor"],
                  start_day=start_day)
        self.twins[pid] = DigitalTwin(pid, self._ehr_raw(pid), self.ehr_encoded.loc[pid], self.predictor)
        self._warm(w, [pid], (main.minute - w.minute) // 5)
        self.worlds.append(w)
        self.where[pid] = (w, 0)
        if pid not in self.ids:
            self.ids.append(pid)
        self.audit.seed_consent([pid], {pid: True})

    # ------------------------------------------------------------------------------------------
    # patient-app actions performed in the virtual patient's world (Quick Log)
    # ------------------------------------------------------------------------------------------
    def perform(self, pid: str, action: dict) -> dict:
        """Make the virtual patient *do* what they logged, so the twin sees it through the data.

        ASSUMPTION (simulation only): in a real deployment a log records an action that already happened.
        Here the log also triggers that action in the simulated world.
        """
        from data_gen.meals import MEAL_BY_NAME, Meal

        with self.lock:
            w, i = self.where[pid]
            kind = action["kind"]
            if kind == "meal":
                base = MEAL_BY_NAME.get(action["meal"])
                portion = {"small": 0.7, "regular": 1.0, "large": 1.3}[action.get("portion", "regular")]
                meal = Meal(base.name, f"{base.label} (logged in app)", base.carbs, base.fast_frac, base.slot, base.veg, base.staple)
                w._meal(i, w.minute, meal, portion, injected=True)
                return {"carbs": round(base.carbs * portion)}
            if kind == "exercise":
                lvl = {"light": 0.3, "moderate": 0.5, "brisk": 0.6}[action.get("intensity", "moderate")]
                w.inject_exercise(i, int(action["minutes"]), lvl)
                return {}
            if kind == "med":
                if action["status"] == "missed":
                    w.inject_missed_meds(i, 8)
                else:  # one dose of the *existing* prescription (metformin 500 mg); never a new dose
                    dose = 0.5 if self.patients.loc[pid, "metformin_mg"] else 0.0
                    if dose:
                        w._put("met", i, w.minute, dose)
                    w._add_event(Event(w.minute, i, "med", "metformin" if dose else "other",
                                       "Medicine taken (logged in app)", dose, True, dose, True))
                return {}
            return {}  # symptoms: no physiological effect

    def _ehr_raw(self, pid: str) -> dict:
        r = self.patients.loc[pid].to_dict()
        return {k: (v.item() if isinstance(v, np.generic) else v) for k, v in r.items()}

    def clock(self) -> str:
        return self.world.now().isoformat()

    # ------------------------------------------------------------------------------------------
    # ingestion (shared by the internal world and the external /api/ingest endpoint)
    # ------------------------------------------------------------------------------------------
    def ingest(self, pid: str, record: dict, events: list[dict], calibrate: bool = True, predict: bool = True) -> None:
        tw = self.twins[pid]
        clean = {"ts": record["ts"], **{k: record.get(k) for k in DEVICE_FIELDS}}  # data minimisation
        if not calibrate:
            tw._last_cal = pd.Timestamp(record["ts"])
        tw.ingest(clean, events)
        if predict:
            tw.update_prediction(explain=pid in self.focus.values())

    @staticmethod
    def _events_by_patient(world: World, evs: list) -> dict[int, list[dict]]:
        """Only *logged* events reach the twin (unlogged meals stay hidden, as in reality)."""
        by_pid: dict[int, list[dict]] = {}
        for e in evs:
            if e.logged:
                by_pid.setdefault(e.patient, []).append({
                    "ts": (world.start + pd.Timedelta(minutes=e.minute)).isoformat(), "type": e.type, "name": e.name,
                    "label": e.label, "logged_amount": e.logged_amount, "injected": e.injected})
        return by_pid

    def _ingest_block(self, rec: dict, evs: list, calibrate: bool = True, predict: bool = False,
                      world: World | None = None, ids: list[str] | None = None) -> None:
        world = world or self.world
        ids = ids or world.ids
        ts = world.now()
        by_pid = self._events_by_patient(world, evs)
        for i, pid in enumerate(ids):
            record = {"ts": ts.isoformat(), **{k: (None if pd.isna(rec[k][i]) else float(rec[k][i])) for k in DEVICE_FIELDS}}
            self.ingest(pid, record, by_pid.get(i, []), calibrate=calibrate, predict=predict)

    def tick(self) -> dict:
        """Advance the internal world by 5 simulated minutes and update every twin."""
        with self.lock:
            t0 = time.time()
            before = {pid: len(tw.alerts) for pid, tw in self.twins.items()}
            for w in self.worlds:  # all worlds share one clock
                rec, evs = w.advance_block()
                self._ingest_block(rec, evs, predict=True, world=w, ids=[p for p, (ww, _) in self.where.items() if ww is w])
            new_alerts = []
            for pid, tw in self.twins.items():
                for a in tw.alerts[before[pid]:]:
                    new_alerts.append(a)
                    self.audit.log("twin-engine", "alert_raised", pid, {k: a[k] for k in ("id", "level", "risk", "minutes_to_spike")}, ts_sim=a["ts"])
            for hook in self.post_tick_hooks:
                try:
                    hook()
                except Exception:  # noqa: BLE001 - a hook must never stop the clinical stream
                    log.exception("post-tick hook failed")
            self.tick_ms = (time.time() - t0) * 1000
            return {"clock": self.clock(), "new_alerts": new_alerts}

    # ------------------------------------------------------------------------------------------
    def inject(self, pid: str, event: str, actor: str = "demo-operator") -> dict:
        if event not in INJECTIONS:
            raise ValueError(f"unknown event {event}")
        with self.lock:
            w, i = self.where[pid]
            {"heavy_meal": lambda: w.inject_meal(i, 120, 0.8, "Heavy carb meal (injected)"),
             "missed_medication": lambda: w.inject_missed_meds(i, 24),
             "poor_sleep": lambda: w.inject_poor_sleep(i),
             "sensor_dropout": lambda: w.inject_dropout(i, 60),
             "exercise": lambda: w.inject_exercise(i, 30, 0.5),
             "stress": lambda: w.inject_stress(i, 120, 0.9)}[event]()
            self.audit.log(actor, "inject_event", pid, {"event": event, "description": INJECTIONS[event]}, ts_sim=self.clock())
        return {"ok": True, "event": event, "description": INJECTIONS[event], "clock": self.clock()}

    def cohort(self) -> list[dict]:
        with self.lock:
            return [tw.summary() for tw in self.twins.values()]

    def detail(self, pid: str) -> dict:
        with self.lock:
            tw = self.twins[pid]
            if tw.prediction is None or "explanation" not in tw.prediction or tw.prediction.get("explanation_stale"):
                tw.update_prediction(explain=True)
            d = tw.detail()
            d["consent"] = self.audit.consent(pid)
            return d

    def state(self) -> dict:
        return {"clock": self.clock(), "speed": self.speed, "paused": self.paused, "speeds": list(SPEEDS),
                "mode": self.mode, "patients": len(self.ids), "tick_ms": round(self.tick_ms, 1),
                "injections": [{"event": k, "label": v} for k, v in INJECTIONS.items()]}
