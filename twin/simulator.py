"""Personalised physiological simulator held by each twin.

The twin never sees the virtual patient's hidden physiology. It starts from an **EHR-only prior**
(``params_from_ehr`` without latent traits) and personalises itself from data:

1. **Online state sync** (every 5 min): advance the model with the *observed* inputs (logged meals,
   logged medication, measured activity, sleep) and nudge glucose towards the CGM reading
   (a fixed-gain Luenberger observer).
2. **Periodic calibration** (every few simulated hours): grid-search multipliers on insulin
   sensitivity (SI) and basal set-point (Gb) that best replay the last 24 h of CGM. The search runs
   all candidates at once on the vectorised engine.
"""
from __future__ import annotations

from dataclasses import fields

import numpy as np
import pandas as pd

from data_gen.physiology import MinuteInputs, PhysioParams, PhysioState, params_from_ehr, step

OBSERVER_GAIN = 0.35
DEFAULT_FAST_FRAC = 0.6  # absorption split assumed for logged meals (meal type unknown to the twin)
SLEEP_NEED_H = 7.0


def _tile_params(p: PhysioParams, n: int) -> PhysioParams:
    return PhysioParams(**{f.name: np.repeat(getattr(p, f.name)[:1], n) for f in fields(p)})


def _tile_state(s: PhysioState, n: int) -> PhysioState:
    return PhysioState(**{f.name: np.repeat(getattr(s, f.name)[:1], n) for f in fields(s)})


def sleep_multiplier(sleep_h: float) -> float:
    """Twin's estimate of the next-day insulin-sensitivity factor from measured sleep (population need)."""
    return float(np.clip(1 - 0.07 * max(0.0, SLEEP_NEED_H - sleep_h), 0.72, 1.0))


class PersonalizedSimulator:
    """Single-patient simulator with online sync, calibration and counterfactual roll-outs."""

    def __init__(self, ehr_row: pd.Series) -> None:
        self.ehr = ehr_row
        df = ehr_row.to_frame().T.infer_objects()
        self.prior = params_from_ehr(df)
        self.params = params_from_ehr(df)
        self.si_mult = 1.0
        self.gb_mult = 1.0
        self.state = PhysioState.initial(self.params)
        self.calibration_rmse: float | None = None
        self.n_calibrations = 0
        self.insulin_type = str(ehr_row.get("insulin_type", "none"))

    # ------------------------------------------------------------------------------------------
    def inputs_from_row(self, row: dict, n: int = 1) -> MinuteInputs:
        """Per-minute inputs reconstructed from one observed 5-min record (amounts spread over 5 min)."""
        z = np.zeros(n)
        carbs_mg = float(row.get("carbs", 0) or 0) * 1000 / 5
        ins = float(row.get("ins_units", 0) or 0) / 5
        premix = self.insulin_type == "premix_30_70"
        act = row.get("activity")
        return MinuteInputs(
            carb_fast=z + carbs_mg * DEFAULT_FAST_FRAC, carb_slow=z + carbs_mg * (1 - DEFAULT_FAST_FRAC),
            activity=z + (0.0 if act is None or np.isnan(act) else float(act)), stress=z.copy(),
            met=z + float(row.get("med_met", 0) or 0) / 5, su=z + float(row.get("med_su", 0) or 0) / 5,
            dpp4=z + float(row.get("med_dpp4", 0) or 0) / 5, sglt2=z + float(row.get("med_sglt2", 0) or 0) / 5,
            ins_rapid=z + (0.3 * ins if premix else 0.0), ins_nph=z + (0.7 * ins if premix else 0.0),
            ins_basal=z + (0.0 if premix else ins),
        )

    def sync(self, row: dict, minute_of_day: int, last_sleep_h: float | None = None) -> float:
        """Advance 5 min with observed inputs and correct towards the CGM reading. Returns the model's
        glucose *before* correction (one-step-ahead prediction)."""
        if last_sleep_h is not None:
            self.state.sleep_mult[:] = sleep_multiplier(last_sleep_h)
        u = self.inputs_from_row(row)
        for k in range(5):
            step(self.state, self.params, u, (minute_of_day - 5 + k) % 1440)
        pred = float(self.state.Gi[0])
        cgm = row.get("cgm")
        if cgm is not None and not np.isnan(cgm):
            err = float(cgm) - pred
            self.state.Gi += OBSERVER_GAIN * err
            self.state.G += OBSERVER_GAIN * err
        return pred

    # ------------------------------------------------------------------------------------------
    def calibrate(self, frame: pd.DataFrame, last_sleep_h: float = 7.0) -> dict:
        """Grid-search SI / Gb multipliers that best replay ``frame`` (>= 12 h of 5-min rows)."""
        frame = frame.tail(288).reset_index(drop=True)
        cgm = frame["cgm"].to_numpy(float)
        if np.isfinite(cgm).sum() < 60:
            return {"skipped": True}
        si_grid = np.array([0.4, 0.55, 0.7, 0.85, 1.0, 1.2, 1.45, 1.75, 2.1])
        gb_grid = np.array([0.8, 0.88, 0.95, 1.0, 1.06, 1.13, 1.2])
        S, B = np.meshgrid(si_grid, gb_grid, indexing="ij")
        n = S.size
        p = _tile_params(self.prior, n)
        p.SI = p.SI * S.ravel()
        p.Gb = p.Gb * B.ravel()
        first = np.flatnonzero(np.isfinite(cgm))[0]
        st = PhysioState.initial(p)
        st.G[:] = cgm[first]
        st.Gi[:] = cgm[first]
        st.sleep_mult[:] = sleep_multiplier(last_sleep_h)
        ts = pd.to_datetime(frame["ts"])
        mod = (ts.dt.hour * 60 + ts.dt.minute).to_numpy()
        preds = np.full((len(frame), n), np.nan)
        rows = frame.to_dict("records")
        warm = 36  # 3 h burn-in where observer sync is applied (unknown initial gut/drug state)
        for i, row in enumerate(rows):
            u = self.inputs_from_row(row, n)
            for k in range(5):
                step(st, p, u, (mod[i] - 5 + k) % 1440)
            preds[i] = st.Gi
            if i < warm and np.isfinite(cgm[i]):
                st.G += 0.5 * (cgm[i] - st.Gi)
                st.Gi += 0.5 * (cgm[i] - st.Gi)
        m = np.isfinite(cgm)
        m[:warm] = False
        rmse = np.sqrt(np.nanmean((preds[m] - cgm[m, None]) ** 2, axis=0))
        # mild shrinkage towards the prior (multiplier 1) to avoid over-fitting a single day
        penalty = 4.0 * (np.log(S.ravel()) ** 2 + 4 * np.log(B.ravel()) ** 2)
        best = int(np.argmin(rmse + penalty))
        self.si_mult, self.gb_mult = float(S.ravel()[best]), float(B.ravel()[best])
        self.params.SI = self.prior.SI * self.si_mult
        self.params.Gb = self.prior.Gb * self.gb_mult
        self.calibration_rmse = float(rmse[best])
        self.n_calibrations += 1
        return {"si_mult": self.si_mult, "gb_mult": self.gb_mult, "rmse": self.calibration_rmse,
                "prior_rmse": float(rmse[np.argmin(np.abs(S.ravel() - 1) + np.abs(B.ravel() - 1))])}

    # ------------------------------------------------------------------------------------------
    def rollout(self, schedules: list[dict[str, np.ndarray]], start_minute_of_day: int, horizon_min: int,
                sleep_mults: list[float] | None = None) -> np.ndarray:
        """Simulate several input schedules in parallel from the current state.

        Each schedule maps MinuteInputs field names to per-minute arrays of length ``horizon_min``.
        Returns glucose (interstitial, as a CGM would read) every 5 min, shape (n_schedules, horizon/5).
        """
        n = len(schedules)
        p = _tile_params(self.params, n)
        st = _tile_state(self.state, n)
        if sleep_mults is not None:
            st.sleep_mult[:] = np.asarray(sleep_mults)
        names = [f.name for f in fields(MinuteInputs)]
        mats = {k: np.stack([s.get(k, np.zeros(horizon_min)) for s in schedules]) for k in names}
        out = np.empty((n, horizon_min // 5))
        for t in range(horizon_min):
            u = MinuteInputs(**{k: mats[k][:, t] for k in names})
            step(st, p, u, (start_minute_of_day + t) % 1440)
            if (t + 1) % 5 == 0:
                out[:, (t + 1) // 5 - 1] = st.Gi
        return out

    def describe(self) -> dict:
        return {"si_mult": round(self.si_mult, 2), "gb_mult": round(self.gb_mult, 2),
                "SI": float(self.params.SI[0]), "Gb": round(float(self.params.Gb[0]), 1),
                "calibration_rmse": None if self.calibration_rmse is None else round(self.calibration_rmse, 1),
                "n_calibrations": self.n_calibrations}
