"""What-if engine: counterfactual glucose trajectories from the twin's current state.

A *scenario* is a named list of interventions applied together, e.g.::

    {"name": "Walk 20 min now", "interventions": [{"type": "exercise", "minutes": 20, "intensity": "moderate"}]}
    {"name": "Dinner 60 g at 21:00", "interventions": [{"type": "meal", "carbs": 60, "at": "21:00"}]}

Supported intervention types
    meal        carbs (g), gi = low|medium|high, at "HH:MM" or in_min (clock times are all placed on one
                day: today, or tomorrow if any of them has already passed)
    exercise    minutes, intensity = light|moderate|vigorous, at / in_min
    medication  drug = metformin|sulfonylurea|rapid_insulin|basal_insulin, dose (mg or U), at / in_min
    sleep       hours (sets the insulin-sensitivity factor implied by that night's sleep)

All scenarios and the baseline ("no new events") are simulated in parallel with the twin's
personalised simulator. Results are physiological-model estimates for discussion, **not**
treatment advice.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from twin.simulator import PersonalizedSimulator, sleep_multiplier

GI_FAST = {"low": 0.35, "medium": 0.6, "high": 0.8}
INTENSITY = {"light": 0.25, "moderate": 0.5, "vigorous": 0.8}
MAX_HORIZON = 30 * 60
REFERENCE_MEAL = {"type": "meal", "carbs": 50, "gi": "medium", "in_min": 30, "reference": True}


def _clock(iv: dict, day: pd.Timestamp) -> pd.Timestamp:
    hh, mm = (int(x) for x in str(iv["at"]).split(":"))
    return day + pd.Timedelta(hours=hh, minutes=mm)


def _base_day(ivs: list[dict], now: pd.Timestamp) -> pd.Timestamp:
    """Day on which clock-time interventions are placed. All of them go on the same day, so
    "dinner at 19:00 vs 21:00" compares like with like: today if every time is still ahead, else tomorrow."""
    today = now.normalize()
    timed = [iv for iv in ivs if iv.get("at")]
    if any(_clock(iv, today) < now for iv in timed):
        return today + pd.Timedelta(days=1)
    return today


def _offset(iv: dict, now: pd.Timestamp, day: pd.Timestamp | None = None) -> int:
    if iv.get("at"):
        return int((_clock(iv, day if day is not None else _base_day([iv], now)) - now).total_seconds() // 60)
    return max(int(iv.get("in_min", 0)), 0)


def _schedule(ivs: list[dict], now: pd.Timestamp, horizon: int, day: pd.Timestamp) -> tuple[dict[str, np.ndarray], float | None]:
    s = {k: np.zeros(horizon) for k in ("carb_fast", "carb_slow", "activity", "met", "su", "ins_rapid", "ins_basal")}
    sleep_h = None
    for iv in ivs:
        t = _offset(iv, now, day)
        if t >= horizon:
            continue
        typ = iv.get("type")
        if typ == "meal":
            mg = float(iv.get("carbs", 0)) * 1000
            ff = GI_FAST.get(iv.get("gi", "medium"), 0.6)
            dur = min(15, horizon - t)
            s["carb_fast"][t : t + dur] += mg * ff / 15
            s["carb_slow"][t : t + dur] += mg * (1 - ff) / 15
        elif typ == "exercise":
            dur = int(iv.get("minutes", 20))
            s["activity"][t : t + dur] = INTENSITY.get(iv.get("intensity", "moderate"), 0.5)
        elif typ == "medication":
            drug, dose = iv.get("drug", "metformin"), float(iv.get("dose", 500))
            if drug == "metformin":
                s["met"][t] += dose / 1000
            elif drug == "sulfonylurea":
                s["su"][t] += dose
            elif drug == "rapid_insulin":
                s["ins_rapid"][t] += dose
            elif drug == "basal_insulin":
                s["ins_basal"][t] += dose
        elif typ == "sleep":
            sleep_h = float(iv.get("hours", 7))
    return s, sleep_h


def _summary(traj: np.ndarray, base: np.ndarray | None) -> dict:
    above = np.clip(traj - 180, 0, None)
    out = {"peak": round(float(traj.max()), 1), "min": round(float(traj.min()), 1), "mean": round(float(traj.mean()), 1),
           "minutes_above_180": int((traj > 180).sum() * 5), "minutes_below_70": int((traj < 70).sum() * 5),
           "auc_above_180": round(float(above.sum() * 5), 0)}
    if base is not None:
        out["delta_peak"] = round(out["peak"] - float(base.max()), 1)
        out["delta_minutes_above_180"] = out["minutes_above_180"] - int((base > 180).sum() * 5)
        out["delta_mean"] = round(out["mean"] - float(base.mean()), 1)
    return out


def run_what_if(sim: PersonalizedSimulator, now: pd.Timestamp, scenarios: list[dict], horizon_min: int | None = None) -> dict:
    """Simulate baseline + scenarios. Returns trajectories every 5 min and comparison summaries."""
    notes: list[str] = []
    scenarios = [dict(s, interventions=list(s.get("interventions", []))) for s in scenarios]
    all_ivs = [iv for s in scenarios for iv in s["interventions"]]
    needs_ref = any(iv.get("type") == "sleep" for iv in all_ivs) and not any(iv.get("type") == "meal" for iv in all_ivs)
    if needs_ref:
        notes.append("Sleep changes insulin sensitivity. To make the effect visible, all trajectories include a "
                     "standard 50 g breakfast 30 min after the start.")
    day = _base_day(all_ivs, now)
    if day > now.normalize() and any(iv.get("at") for iv in all_ivs):
        notes.append(f"Clock times are scheduled for {day.strftime('%a %d %b')} because at least one has already passed today.")
    last = max([_offset(iv, now, day) for iv in all_ivs] + [0])
    horizon = int(horizon_min or min(max(240, last + 180), MAX_HORIZON))
    horizon -= horizon % 5
    base_ivs = [REFERENCE_MEAL] if needs_ref else []
    scheds, sleeps = [], []
    for ivs in [base_ivs] + [s["interventions"] + base_ivs for s in scenarios]:
        sc, sh = _schedule(ivs, now, horizon, day)
        scheds.append(sc)
        sleeps.append(float(sim.state.sleep_mult[0]) if sh is None else sleep_multiplier(sh))
    mod = now.hour * 60 + now.minute
    traj = sim.rollout(scheds, mod, horizon, sleep_mults=sleeps)
    times = [(now + pd.Timedelta(minutes=5 * (k + 1))).isoformat() for k in range(traj.shape[1])]
    base = traj[0]
    return {
        "start": now.isoformat(), "horizon_min": horizon, "times": times,
        "baseline": {"name": "Baseline (no new events)", "trajectory": np.round(base, 1).tolist(), "summary": _summary(base, None)},
        "scenarios": [{"name": s.get("name", f"Scenario {i + 1}"), "interventions": s["interventions"],
                       "trajectory": np.round(traj[i + 1], 1).tolist(), "summary": _summary(traj[i + 1], base)}
                      for i, s in enumerate(scenarios)],
        "notes": notes + ["Physiological-model estimate from the personalised twin. Not a treatment recommendation."],
        "simulator": sim.describe(),
    }
