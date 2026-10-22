"""Evaluation metrics for spike classification and glucose forecasting."""
from __future__ import annotations

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score


def classification(y: np.ndarray, p: np.ndarray, thr: float | None = None) -> dict[str, float]:
    y = np.asarray(y).astype(int)
    p = np.asarray(p, dtype=float)
    out = {"n": int(len(y)), "prevalence": float(y.mean())}
    if len(np.unique(y)) < 2:
        return {**out, "roc_auc": float("nan"), "pr_auc": float("nan"), "brier": float("nan")}
    out.update(roc_auc=float(roc_auc_score(y, p)), pr_auc=float(average_precision_score(y, p)),
               brier=float(brier_score_loss(y, p)))
    if thr is not None:
        pred = p >= thr
        tp, fp = int((pred & (y == 1)).sum()), int((pred & (y == 0)).sum())
        fn, tn = int((~pred & (y == 1)).sum()), int((~pred & (y == 0)).sum())
        out.update(sensitivity=tp / max(tp + fn, 1), specificity=tn / max(tn + fp, 1), ppv=tp / max(tp + fp, 1))
    return out


def regression(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    m = ~np.isnan(y_true) & ~np.isnan(y_pred)
    e = y_pred[m] - y_true[m]
    return {"rmse": float(np.sqrt(np.mean(e**2))), "mae": float(np.mean(np.abs(e))), "n": int(m.sum())}


def interval_coverage(y_true: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> float:
    m = ~np.isnan(y_true)
    return float(np.mean((y_true[m] >= lo[m]) & (y_true[m] <= hi[m])))


def reliability(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict[str, float]]:
    """Calibration curve on equal-width probability bins."""
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    out = []
    for b in range(bins):
        m = idx == b
        if m.sum() >= 20:
            out.append({"bin": float((edges[b] + edges[b + 1]) / 2), "pred": float(p[m].mean()), "obs": float(y[m].mean()), "n": int(m.sum())})
    return out


def bootstrap_ci(y: np.ndarray, p: np.ndarray, groups: np.ndarray, fn, n_boot: int = 200, seed: int = 0) -> tuple[float, float]:
    """Patient-level (cluster) bootstrap 95% CI for a metric fn(y, p)."""
    rng = np.random.default_rng(seed)
    ug = np.unique(groups)
    pos = {g: np.flatnonzero(groups == g) for g in ug}
    vals = []
    for _ in range(n_boot):
        pick = rng.choice(ug, len(ug), replace=True)
        ix = np.concatenate([pos[g] for g in pick])
        if len(np.unique(y[ix])) == 2:
            vals.append(fn(y[ix], p[ix]))
    if not vals:
        return float("nan"), float("nan")
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))
