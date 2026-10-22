"""Virtual-patient world simulator: lifestyle -> physiology -> wearable / CGM signals.

The same engine powers:

* batch synthetic dataset generation (``data_gen.generate``), and
* the live demo stream (``backend.stream``), where clinicians can *inject* events (heavy meal,
  missed medication, poor-sleep night, sensor dropout, exercise, stress) that change the future
  physiology and are therefore seen by the predictor only through the data, as in reality.

Inputs are planned day by day into a rolling 3-day per-minute buffer (current day + 2 days of
look-ahead, needed because sleep crosses midnight). Every 5 minutes the world emits one wearable
record per patient.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
import pandas as pd

from data_gen.meals import MEAL_BY_NAME, Meal, candidates
from data_gen.physiology import MinuteInputs, PhysioParams, PhysioState, step

DAY = 1440
BLOCK = 5
INPUT_CHANNELS = [
    "carb_fast", "carb_slow", "activity", "steps", "stress", "met", "su", "dpp4", "sglt2",
    "ins_rapid", "ins_nph", "ins_basal", "sleep_set", "wear_off",
]
SLEEP_STAGES = {0: "awake", 1: "light", 2: "deep", 3: "rem"}


@dataclass(order=True)
class Event:
    """A discrete event in the world (meal or medication)."""

    minute: int
    patient: int
    type: str  # meal | med
    name: str
    label: str
    amount: float  # true carbs (g) or dose
    logged: bool  # visible in the app/device stream?
    logged_amount: float  # carbs as estimated by the patient / dose recorded by device
    injected: bool = False


def hypnogram(duration: int, poor: bool, rng: np.random.Generator) -> np.ndarray:
    """Generate a per-minute sleep-stage sequence (0 awake, 1 light, 2 deep, 3 REM).

    ASSUMPTION: ~90-min cycles, deep sleep front-loaded, REM back-loaded; poor nights have longer
    latency and more awakenings. Simplified relative to real polysomnography.
    """
    stages: list[int] = [0] * int(rng.integers(20, 50) if poor else rng.integers(8, 25))
    k = 0
    while len(stages) < duration:
        cyc = int(rng.integers(80, 110))
        deep = int(cyc * max(0.32 - 0.08 * k, 0.03) * (0.7 if poor else 1.0))
        rem = int(cyc * min(0.08 + 0.07 * k, 0.35))
        light = cyc - deep - rem
        stages += [1] * (light // 2) + [2] * deep + [1] * (light - light // 2) + [3] * rem
        k += 1
    arr = np.array(stages[:duration], dtype=np.int8)
    n_wake = rng.poisson(duration / 60 * (1.5 if poor else 0.4))
    for _ in range(n_wake):
        s = int(rng.integers(0, max(duration - 5, 1)))
        arr[s : s + int(rng.integers(5, 20) if poor else rng.integers(2, 8))] = 0
    return arr


class World:
    """Ground-truth simulator for N virtual patients."""

    def __init__(
        self,
        patients: pd.DataFrame,
        latent: pd.DataFrame,
        params: PhysioParams,
        start: pd.Timestamp,
        seed: int,
        sensor_cfg: dict,
        start_day: int = 0,
    ) -> None:
        self.ids = list(patients.index)
        self.n = len(self.ids)
        self.pat = patients.reset_index()
        self.lat = latent.loc[self.ids].reset_index()
        # attribute-style row access is much faster than DataFrame.iloc inside planning loops
        self._P = [SimpleNamespace(**r) for r in self.pat.to_dict("records")]
        self._L = [SimpleNamespace(**r) for r in self.lat.to_dict("records")]
        self._rest_hr = self.lat["rest_hr"].to_numpy(float)
        self._hrv_base = self.lat["hrv_base"].to_numpy(float)
        self._obese30 = self.pat["bmi"].to_numpy(float) > 30
        self.p = params
        self.state = PhysioState.initial(params)
        self.rng = np.random.default_rng(seed)
        self.start = pd.Timestamp(start)
        self.sensor = sensor_cfg
        self.minute = start_day * DAY  # absolute simulated minute since `start`

        self.buf_start = self.minute
        self.buf = {c: np.zeros((self.n, 3 * DAY), dtype=np.float32) for c in INPUT_CHANNELS}
        self.stage = np.zeros((self.n, 3 * DAY), dtype=np.int8)
        self.events: list[Event] = []
        self.skip_meds_until = np.full(self.n, -1)
        self.wake_next = np.zeros(self.n, dtype=int)  # absolute wake minute of the next morning
        self.last_sleep_h = np.full(self.n, 7.0)
        self.hrv_sleep_mult = np.ones(self.n)

        # sensor state
        self.drift = self.rng.normal(0, 0.03, self.n)
        self.dropout_left = np.zeros(self.n)
        self.compress_left = np.zeros(self.n)
        self.compress_depth = np.ones(self.n)
        self.watch_hr_bias = self.rng.normal(0, 1.5, self.n)

        day0 = self.minute // DAY
        for i in range(self.n):
            self._plan_night(i, day0 - 1, first=True)
        self._plan_day(day0)
        self._plan_day(day0 + 1)

    # ------------------------------------------------------------------------------------------
    # planning helpers
    # ------------------------------------------------------------------------------------------
    def _put(self, ch: str, i: int, minute: int, values: np.ndarray | float, length: int = 1, add: bool = True) -> None:
        """Write ``values`` into channel ``ch`` for patient ``i`` from absolute ``minute``."""
        a = minute - self.buf_start
        b = a + length
        lo, hi = max(a, 0), min(b, 3 * DAY)
        if lo >= hi:
            return
        vals = np.broadcast_to(np.asarray(values, dtype=np.float32), (length,))[lo - a : hi - a]
        if add:
            self.buf[ch][i, lo:hi] += vals
        else:
            self.buf[ch][i, lo:hi] = vals

    def _add_event(self, ev: Event) -> None:
        bisect.insort(self.events, ev)

    def _plan_night(self, i: int, day: int, first: bool = False, force_poor: bool = False) -> None:
        """Plan the sleep that starts on the evening of ``day`` and ends the next morning."""
        lat = self._L[i]
        weekend_next = (self.start + pd.Timedelta(days=day + 1)).dayofweek >= 5
        poor = force_poor or self.rng.random() < lat.poor_sleep_prob
        dur_h = self.rng.normal(lat.sleep_h_mean, 0.5) + (0.5 if weekend_next else 0)
        if poor:
            dur_h = min(dur_h - self.rng.uniform(1.5, 2.8), 5.2)
        dur_h = float(np.clip(dur_h, 3.5, 9.5))
        wake = int((day + 1) * DAY + (lat.wake_h + (0.6 if weekend_next else 0)) * 60 + self.rng.normal(0, 20))
        dur = int(dur_h * 60)
        bed = wake - dur
        hyp = hypnogram(dur, poor, self.rng)
        a = bed - self.buf_start
        lo, hi = max(a, 0), min(a + dur, 3 * DAY)
        if hi > lo:
            self.stage[i, lo:hi] = hyp[lo - a : hi - a]
        slept_h = float((hyp > 0).sum() / 60)
        # ASSUMPTION: each hour of sleep debt cuts next-day insulin sensitivity ~7% (cap ~28%);
        # fragmented nights cost an additional 5%.
        need = float(lat.sleep_need_h)
        mult = np.clip(1 - 0.07 * max(0.0, need - slept_h) - (0.05 if poor else 0.0), 0.72, 1.0)
        self._put("sleep_set", i, wake, mult, add=False)
        self.wake_next[i] = wake
        if first:
            self.state.sleep_mult[i] = mult
            self.last_sleep_h[i] = slept_h

    def _meal(self, i: int, minute: int, meal: Meal, scale: float, injected: bool = False) -> None:
        lat = self._L[i]
        carbs = float(meal.carbs * scale)
        mg = carbs * 1000
        eat = 15  # minutes spent eating
        self._put("carb_fast", i, minute, mg * meal.fast_frac / eat, eat)
        self._put("carb_slow", i, minute, mg * (1 - meal.fast_frac) / eat, eat)
        logged = injected or self.rng.random() < lat.meal_log_prob
        est = carbs * float(self.rng.lognormal(0, 0.22)) if not injected else carbs
        self._add_event(Event(minute, i, "meal", meal.name, meal.label, round(carbs, 1), bool(logged),
                              round(est, 0) if logged else 0.0, injected))

    def _dose(self, i: int, minute: int, drug: str, ch: str, amount: float, label: str, prob: float) -> None:
        if minute < self.skip_meds_until[i] or self.rng.random() > prob:
            return
        self._put(ch, i, minute, amount)
        self._add_event(Event(minute, i, "med", drug, label, amount, True, amount))

    def _activity(self, i: int, minute: int, dur: int, level: float, spm: float) -> None:
        self._put("activity", i, minute, level, dur, add=False)
        self._put("steps", i, minute, self.rng.poisson(spm, dur).astype(np.float32), dur, add=False)

    def _plan_day(self, day: int) -> None:
        """Plan meals, medication, activity, stress, wearable gaps and the following night."""
        weekend = (self.start + pd.Timedelta(days=day)).dayofweek >= 5
        d0 = day * DAY
        for i in range(self.n):
            pt, lat = self._P[i], self._L[i]
            rng = self.rng
            wake = int(self.wake_next[i])
            portion = float(lat.portion) * (1.1 if weekend else 1.0)
            veg, staple = pt.diet == "vegetarian", pt.staple

            def pick(slot: str) -> Meal:
                opts, w = candidates(slot, veg, staple)
                return opts[rng.choice(len(opts), p=w)]

            jitter = lambda: float(rng.lognormal(0, 0.15))  # noqa: E731
            # background awake activity (household / commute steps)
            a0 = wake - self.buf_start
            day_end = d0 + DAY - self.buf_start
            bg = rng.poisson(2.5 * lat.base_activity, max(day_end - a0, 0)).astype(np.float32)
            self._put("steps", i, wake, bg, len(bg))
            self._put("activity", i, wake, 0.03 * lat.base_activity, len(bg))
            for _ in range(rng.poisson(5 * lat.base_activity)):
                s = d0 + int(rng.uniform(8.5, 20) * 60)
                self._activity(i, s, int(rng.integers(5, 25)), 0.22, 60 * lat.base_activity)

            # meals
            breakfast = wake + int(rng.uniform(40, 100))
            if rng.random() > 0.04:
                self._meal(i, breakfast, pick("breakfast"), portion * jitter())
            lunch = d0 + int(lat.lunch_h * 60 + rng.normal(0, 25) + (20 if weekend else 0))
            self._meal(i, lunch, pick("lunch"), portion * jitter())
            if rng.random() < lat.snack_prob:
                self._meal(i, d0 + int(rng.uniform(16.8, 18.5) * 60), pick("snack"), jitter())
            dinner = d0 + int(lat.dinner_h * 60 + rng.normal(0, 30) + (30 if weekend else 0))
            self._meal(i, dinner, pick("dinner"), portion * jitter())
            if rng.random() < lat.sweet_prob * (1.8 if weekend else 1.0):
                self._meal(i, dinner + int(rng.integers(15, 40)), pick("sweet"), jitter())

            # medication (prescription from EHR; adherence is hidden)
            adh = float(lat.adherence)
            met = int(pt.metformin_mg)
            if met:
                am, pm = {1000: (0.5, 0.5), 1500: (0.5, 1.0), 2000: (1.0, 1.0)}.get(met, (met / 2000, met / 2000))
                self._dose(i, breakfast + 5, "metformin", "met", am, f"Metformin {int(am*1000)} mg", adh)
                self._dose(i, dinner + 5, "metformin", "met", pm, f"Metformin {int(pm*1000)} mg", adh - 0.05)
            if pt.sulfonylurea_mg:
                self._dose(i, breakfast - 20, "sulfonylurea", "su", float(pt.sulfonylurea_mg),
                           f"Glimepiride {pt.sulfonylurea_mg} mg", adh)
            if pt.dpp4:
                self._dose(i, breakfast, "dpp4", "dpp4", 1.0, "Teneligliptin 20 mg", adh)
            if pt.sglt2:
                self._dose(i, breakfast, "sglt2", "sglt2", 1.0, "Dapagliflozin 10 mg", adh)
            units = float(pt.insulin_units_day)
            if pt.insulin_type == "premix_30_70" and units > 0:
                for t, frac in ((breakfast - 15, 0.6), (dinner - 15, 0.4)):
                    u = round(units * frac)
                    if t >= self.skip_meds_until[i] and rng.random() < adh + 0.05:
                        self._put("ins_rapid", i, t, 0.3 * u)
                        self._put("ins_nph", i, t, 0.7 * u)
                        self._add_event(Event(t, i, "med", "insulin_premix", f"Premix 30/70 {u} U", u, True, u))
            elif pt.insulin_type == "basal_glargine" and units > 0:
                self._dose(i, d0 + 22 * 60, "insulin_basal", "ins_basal", units, f"Glargine {int(units)} U", adh + 0.05)

            # exercise habits
            if lat.walk_habit and rng.random() < (0.5 if weekend else 0.7):
                self._activity(i, wake + int(rng.uniform(10, 40)), int(rng.uniform(25, 45)), 0.5, 105)
            if lat.post_dinner_walk and rng.random() < 0.6:
                self._activity(i, dinner + int(rng.uniform(15, 30)), int(rng.uniform(10, 25)), 0.4, 95)

            # stress episodes on workdays
            if not weekend and rng.random() < lat.stress_prob:
                self._put("stress", i, d0 + int(rng.uniform(10, 17) * 60), rng.uniform(0.4, 1.0),
                          int(rng.uniform(60, 180)), add=False)

            # smartwatch off-wrist (charging) gap
            if rng.random() < 0.6:
                self._put("wear_off", i, d0 + int(rng.uniform(9, 19) * 60), 1.0, int(rng.uniform(30, 75)), add=False)

            # the following night (sets tomorrow's wake time and insulin-sensitivity factor)
            self._plan_night(i, day)
            # no steps / activity while asleep
            asleep = self.stage[i] > 0
            self.buf["steps"][i, asleep] = 0
            self.buf["activity"][i, asleep] = 0

    # ------------------------------------------------------------------------------------------
    # live-demo injections
    # ------------------------------------------------------------------------------------------
    def inject_meal(self, i: int, carbs: float = 120, fast_frac: float = 0.75, label: str = "Heavy carb meal") -> None:
        meal = Meal("injected_meal", label, carbs, fast_frac, "dinner", True, "any")
        self._meal(i, self.minute, meal, 1.0, injected=True)

    def inject_missed_meds(self, i: int, hours: float = 24) -> None:
        until = self.minute + int(hours * 60)
        self.skip_meds_until[i] = until
        a, b = self.minute - self.buf_start, min(until - self.buf_start, 3 * DAY)
        for ch in ("met", "su", "dpp4", "sglt2", "ins_rapid", "ins_nph", "ins_basal"):
            self.buf[ch][i, a:b] = 0
        self.events = [e for e in self.events if not (e.patient == i and e.type == "med" and self.minute <= e.minute < until)]

    def inject_poor_sleep(self, i: int) -> None:
        """Make the coming night short and fragmented (same wake time, ~4 h asleep)."""
        a = self.minute - self.buf_start
        nxt = np.nonzero(self.buf["sleep_set"][i, a:])[0]
        if len(nxt) == 0:
            return
        wake = self.minute + int(nxt[0])
        night_day = wake // DAY - 1
        # clear the currently planned night, then plan a poor one ending at the same wake time
        lo = max((night_day * DAY + 18 * 60) - self.buf_start, a)
        hi = wake - self.buf_start
        self.stage[i, lo:hi] = 0
        dur = int(self.rng.uniform(3.8, 4.4) * 60)
        hyp = hypnogram(dur, True, self.rng)
        s = max(wake - dur - self.buf_start, a)
        if hi <= s:
            return
        self.stage[i, s:hi] = hyp[-(hi - s):]
        slept = (hyp > 0).sum() / 60
        need = float(self._L[i].sleep_need_h)
        self.buf["sleep_set"][i, hi] = np.clip(1 - 0.07 * max(0, need - slept) - 0.05, 0.72, 1.0)
        self.buf["steps"][i, s:hi] = 0
        self.buf["activity"][i, s:hi] = 0

    def inject_dropout(self, i: int, minutes: int = 60) -> None:
        self.dropout_left[i] = max(self.dropout_left[i], minutes)

    def inject_exercise(self, i: int, minutes: int = 30, level: float = 0.5) -> None:
        self._activity(i, self.minute, minutes, level, 105)

    def inject_stress(self, i: int, minutes: int = 120, level: float = 0.9) -> None:
        self._put("stress", i, self.minute, level, minutes, add=False)

    # ------------------------------------------------------------------------------------------
    # simulation
    # ------------------------------------------------------------------------------------------
    def _roll(self) -> None:
        for c in INPUT_CHANNELS:
            self.buf[c][:, :-DAY] = self.buf[c][:, DAY:]
            self.buf[c][:, -DAY:] = 0
        self.stage[:, :-DAY] = self.stage[:, DAY:]
        self.stage[:, -DAY:] = 0
        self.buf_start += DAY
        self._plan_day(self.buf_start // DAY + 1)

    def advance_block(self) -> tuple[dict[str, np.ndarray], list[Event]]:
        """Simulate 5 minutes for all patients; return the emitted wearable record and events."""
        act_sum = np.zeros(self.n)
        stress_sum = np.zeros(self.n)
        steps = np.zeros(self.n)
        wear_off = np.zeros(self.n, dtype=bool)
        for _ in range(BLOCK):
            if self.minute - self.buf_start >= DAY:
                self._roll()
            c = self.minute - self.buf_start
            col = {k: v[:, c].astype(float) for k, v in self.buf.items()}
            woke = col["sleep_set"] > 0
            if woke.any():
                self.state.sleep_mult[woke] = col["sleep_set"][woke]
                self.last_sleep_h[woke] = (self.stage[woke, max(c - 720, 0):c] > 0).sum(axis=1) / 60
                self.hrv_sleep_mult[woke] = np.clip(0.75 + 0.04 * self.last_sleep_h[woke], 0.8, 1.05)
            u = MinuteInputs(
                carb_fast=col["carb_fast"], carb_slow=col["carb_slow"], activity=col["activity"],
                stress=col["stress"], met=col["met"], su=col["su"], dpp4=col["dpp4"], sglt2=col["sglt2"],
                ins_rapid=col["ins_rapid"], ins_nph=col["ins_nph"], ins_basal=col["ins_basal"],
            )
            step(self.state, self.p, u, self.minute % DAY)
            act_sum += col["activity"]
            stress_sum += col["stress"]
            steps += col["steps"]
            wear_off |= col["wear_off"] > 0
            self.minute += 1

        c = self.minute - 1 - self.buf_start
        stage = self.stage[:, c].astype(int)
        rec = self._emit(act_sum / BLOCK, stress_sum / BLOCK, steps, stage, wear_off)
        out: list[Event] = []
        while self.events and self.events[0].minute < self.minute:
            out.append(self.events.pop(0))
        return rec, out

    def _emit(self, act: np.ndarray, stress: np.ndarray, steps: np.ndarray, stage: np.ndarray,
              wear_off: np.ndarray) -> dict[str, np.ndarray]:
        """Turn the physiological state into noisy sensor readings."""
        rng, cfg, n = self.rng, self.sensor, self.n
        asleep = stage > 0
        G, Gi = self.state.G, self.state.Gi

        # --- CGM -----------------------------------------------------------------------------
        self.drift = 0.999 * self.drift + rng.normal(0, cfg["drift_sd_per_day"] / np.sqrt(288 / 4), n)
        cgm = Gi * (1 + self.drift) * (1 + rng.normal(0, cfg["noise_mult_sd"], n)) + rng.normal(0, cfg["noise_add_sd"], n)
        # compression artefact: false low while lying on the sensor (night only)
        start_c = asleep & (self.compress_left <= 0) & (rng.random(n) < cfg["compression_per_night"] / 90)
        self.compress_left[start_c] = rng.uniform(20, 60, start_c.sum())
        self.compress_depth[start_c] = rng.uniform(0.6, 0.8, start_c.sum())
        comp = (self.compress_left > 0) & asleep
        cgm = np.where(comp, cgm * self.compress_depth, cgm)
        self.compress_left = np.maximum(self.compress_left - BLOCK, 0)
        # dropouts (signal loss / sensor warm-up)
        start_d = (self.dropout_left <= 0) & (rng.random(n) < cfg["dropout_per_day"] / 288)
        self.dropout_left[start_d] = rng.exponential(cfg["dropout_mean_min"], start_d.sum()) + 10
        drop = self.dropout_left > 0
        self.dropout_left = np.maximum(self.dropout_left - BLOCK, 0)
        cgm = np.where(drop, np.nan, np.clip(np.round(cgm), 40, 400))

        # --- smartwatch --------------------------------------------------------------------------
        hr = (self._rest_hr + self.watch_hr_bias - 8 * asleep + 55 * act + 10 * stress
              + 0.02 * np.maximum(G - 180, 0) + rng.normal(0, 2.5, n))
        stage_mult = np.select([stage == 2, stage == 1, stage == 3], [1.35, 1.15, 1.0], 1.0)
        hrv = (self._hrv_base * stage_mult * (1 - 0.35 * stress) * (1 - 0.4 * act) * self.hrv_sleep_mult
               * (1 - 0.0015 * np.maximum(G - 180, 0)) * rng.lognormal(0, 0.12, n))
        spo2 = np.clip(97.2 + rng.normal(0, 0.7, n) - asleep * self._obese30 * rng.exponential(1.0, n), 85, 100)
        skin = 33.0 + 0.8 * asleep - 0.6 * act + rng.normal(0, 0.2, n)
        off = wear_off & ~asleep
        nan = np.nan
        return {
            "minute": np.full(n, self.minute),
            "cgm": cgm,
            "glucose_true": G.copy(),
            "hr": np.where(off, nan, np.round(hr, 1)),
            "hrv_rmssd": np.where(off, nan, np.round(hrv, 1)),
            "steps": np.where(off, nan, steps),
            "activity": np.where(off, nan, np.round(act, 3)),
            "sleep_stage": stage,
            "spo2": np.where(off, nan, np.round(spo2, 1)),
            "skin_temp": np.where(off, nan, np.round(skin, 2)),
            "stress_true": np.round(stress, 2),
        }

    def run(self, days: float, progress: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Simulate ``days`` days; return (wearable records, events) DataFrames."""
        n_blocks = int(days * DAY / BLOCK)
        recs: list[dict[str, np.ndarray]] = []
        evs: list[Event] = []
        for k in range(n_blocks):
            r, e = self.advance_block()
            recs.append(r)
            evs.extend(e)
        return self.records_frame(recs), self.events_frame(evs)

    def records_frame(self, recs: list[dict[str, np.ndarray]]) -> pd.DataFrame:
        if not recs:
            return pd.DataFrame()
        cols = {k: np.stack([r[k] for r in recs], axis=1).ravel() for k in recs[0]}
        df = pd.DataFrame(cols)
        df.insert(0, "patient_id", np.repeat(self.ids, len(recs)))
        df.insert(1, "ts", self.start + pd.to_timedelta(df.pop("minute"), unit="min"))
        df["sleep_stage"] = df["sleep_stage"].astype("int8")
        return df

    def events_frame(self, evs: list[Event]) -> pd.DataFrame:
        cols = ["patient_id", "ts", "type", "name", "label", "amount", "logged", "logged_amount", "injected"]
        if not evs:
            return pd.DataFrame(columns=cols)
        df = pd.DataFrame([e.__dict__ for e in evs])
        df["patient_id"] = [self.ids[i] for i in df.pop("patient")]
        df["ts"] = self.start + pd.to_timedelta(df.pop("minute"), unit="min")
        return df[cols]

    def now(self) -> pd.Timestamp:
        return self.start + pd.Timedelta(minutes=self.minute)


def calibrate_basal(
    patients: pd.DataFrame,
    latent: pd.DataFrame,
    params: PhysioParams,
    start: pd.Timestamp,
    seed: int,
    sensor_cfg: dict,
    days: int = 3,
    iters: int = 3,
) -> PhysioParams:
    """Adjust each patient's basal set-point Gb so that simulated mean glucose matches the
    ADAG estimated average glucose implied by the EHR HbA1c (links EHR -> wearable signals)."""
    from data_gen.physiology import eag_from_hba1c

    target = eag_from_hba1c(patients["hba1c"].to_numpy(float))
    for _ in range(iters):
        w = World(patients, latent, params, start, seed, sensor_cfg, start_day=-days - 1)
        recs, _ = w.run(days)
        mean_g = recs.groupby("patient_id", sort=False)["glucose_true"].mean().loc[w.ids].to_numpy()
        params.Gb = np.clip(params.Gb + 0.9 * (target - mean_g), 70, 320)
    return params


MEAL_LABELS = {k: v.label for k, v in MEAL_BY_NAME.items()}
