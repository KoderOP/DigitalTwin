"""Glycemic metrics shared by data generation, evaluation and the dashboard backend.

Follows the International Consensus on Time in Range (Battelino et al., 2019) where applicable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SPIKE = 180.0
HYPO = 70.0


def spike_onsets(cgm: np.ndarray, thr: float = SPIKE, quiet: int = 6, confirm: int = 2) -> np.ndarray:
    """Boolean mask of *sustained* hyperglycemia onsets in a 5-min CGM series.

    An onset at index t means readings t..t+confirm-1 are all > ``thr``, and the previous ``quiet``
    readings (30 min) contain no reading > thr and at least half of them are valid. This removes
    noise "flicker" around the threshold.
    """
    g = np.asarray(cgm, dtype=float)
    n = len(g)
    above = np.nan_to_num(g, nan=-1) > thr
    valid = ~np.isnan(g)
    out = np.zeros(n, dtype=bool)
    if n < quiet + confirm:
        return out
    conf = above.copy()
    for k in range(1, confirm):
        conf[: n - k] &= above[k:]
        conf[n - k :] = False
    c_above = np.concatenate([[0], np.cumsum(above)])
    c_valid = np.concatenate([[0], np.cumsum(valid)])
    t = np.arange(quiet, n)
    prev_above = c_above[t] - c_above[t - quiet]
    prev_valid = c_valid[t] - c_valid[t - quiet]
    out[t] = conf[t] & (prev_above == 0) & (prev_valid >= quiet // 2)
    return out


def summary_metrics(cgm: pd.Series | np.ndarray) -> dict[str, float]:
    """TIR/TAR/TBR, mean, SD, CV, GMI for a CGM series (NaNs ignored)."""
    g = pd.Series(cgm, dtype=float).dropna()
    if len(g) == 0:
        return {k: float("nan") for k in ("mean", "sd", "cv", "gmi", "tir", "tar", "tar250", "tbr", "tbr54", "coverage")}
    mean = float(g.mean())
    sd = float(g.std(ddof=0))
    return {
        "mean": round(mean, 1),
        "sd": round(sd, 1),
        "cv": round(sd / mean * 100, 1),
        "gmi": round(3.31 + 0.02392 * mean, 2),
        "tir": round(float(((g >= 70) & (g <= 180)).mean() * 100), 1),
        "tar": round(float((g > 180).mean() * 100), 1),
        "tar250": round(float((g > 250).mean() * 100), 1),
        "tbr": round(float((g < 70).mean() * 100), 1),
        "tbr54": round(float((g < 54).mean() * 100), 1),
        "coverage": round(len(g) / max(len(pd.Series(cgm)), 1) * 100, 1),
    }


def agp_profile(ts: pd.Series, cgm: pd.Series, bin_minutes: int = 30) -> list[dict]:
    """Ambulatory Glucose Profile: percentiles (5/25/50/75/95) by time of day."""
    df = pd.DataFrame({"ts": pd.to_datetime(ts), "g": cgm}).dropna()
    if df.empty:
        return []
    df["bin"] = (df.ts.dt.hour * 60 + df.ts.dt.minute) // bin_minutes * bin_minutes
    q = df.groupby("bin")["g"].quantile([0.05, 0.25, 0.5, 0.75, 0.95]).unstack()
    return [
        {"minute": int(b), "p5": round(r[0.05], 1), "p25": round(r[0.25], 1), "p50": round(r[0.5], 1),
         "p75": round(r[0.75], 1), "p95": round(r[0.95], 1)}
        for b, r in q.iterrows()
    ]
