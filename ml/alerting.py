"""Alert policy: thresholds, GREEN/AMBER/RED levels and episode-level alert simulation."""
from __future__ import annotations

import numpy as np
from sklearn.metrics import precision_recall_curve, roc_curve

from common.glycemic import spike_onsets

HORIZON_STEPS = 24  # 120 min


def choose_thresholds(y: np.ndarray, p: np.ndarray, target_sens: float, target_ppv: float) -> dict[str, float]:
    """AMBER = highest threshold with sensitivity >= target; RED = lowest threshold with PPV >= target
    (never below AMBER). Chosen on the validation patients, never on test."""
    fpr, tpr, thr = roc_curve(y, p)
    ok = np.flatnonzero(tpr >= target_sens)
    amber = float(thr[ok[0]]) if len(ok) else 0.5
    amber = min(amber, 1.0)
    prec, rec, thr_pr = precision_recall_curve(y, p)
    ok = np.flatnonzero(prec[:-1] >= target_ppv)
    red = float(thr_pr[ok[0]]) if len(ok) else float(np.quantile(p, 0.95))
    return {"amber": round(amber, 4), "red": round(max(red, amber), 4)}


def alert_level(p: float, thr: dict[str, float]) -> str:
    if p >= thr["red"]:
        return "RED"
    if p >= thr["amber"]:
        return "AMBER"
    return "GREEN"


def simulate_alerts(p: np.ndarray, eligible: np.ndarray, cgm: np.ndarray, thr: float,
                    refractory_steps: int = 12, horizon: int = HORIZON_STEPS) -> dict:
    """Replay a patient's 5-min risk series as a live alerting system.

    * An alert fires when p >= thr while glucose is not already high, at most once per refractory period.
    * A *true* alert is followed by a sustained spike onset within ``horizon`` steps.
    * An onset is *detected* if an alert fired in the ``horizon`` steps before it; lead time is measured
      from the first such alert.

    ``p`` may contain NaN where no prediction was possible (e.g. first 24 h).
    """
    n = len(p)
    onsets = np.flatnonzero(spike_onsets(cgm))
    valid_pred = np.flatnonzero(~np.isnan(p))
    if len(valid_pred) == 0:
        return {"alerts": 0, "true_alerts": 0, "false_alerts": 0, "onsets": 0, "detected": 0, "lead_times": [], "pred_days": 0.0}
    first = valid_pred[0]
    alerts: list[int] = []
    last = -10**9
    fire = np.nan_to_num(p, nan=-1.0) >= thr
    for t in np.flatnonzero(fire & eligible):
        if t - last >= refractory_steps:
            alerts.append(t)
            last = t
    a = np.array(alerts, dtype=int)
    true_mask = np.array([np.any((onsets > t) & (onsets <= t + horizon)) for t in a], dtype=bool)
    counted = onsets[onsets >= first + horizon]
    leads = []
    for o in counted:
        prior = a[(a >= o - horizon) & (a < o)]
        if len(prior):
            leads.append(int((o - prior[0]) * 5))
    return {
        "alerts": int(len(a)), "true_alerts": int(true_mask.sum()), "false_alerts": int((~true_mask).sum()),
        "onsets": int(len(counted)), "detected": int(len(leads)), "lead_times": leads,
        "pred_days": float((n - first) * 5 / 1440),
    }
