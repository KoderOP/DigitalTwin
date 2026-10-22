"""Uniform prediction interface over GBM and deep models for cohort rows."""
from __future__ import annotations

import numpy as np

from ml.dataset import Cohort, matrix, windows
from ml.deep import DeepBundle
from ml.gbm import HORIZONS, GBMModel


def deep_columns(c: Cohort, mode: str) -> tuple[list[str], list[str]]:
    """(tab_cols, static_cols) used by a deep variant."""
    w_cols = [x for x in c.feature_cols if x.startswith(("w_", "t_"))]
    t_cols = [x for x in c.feature_cols if x.startswith("t_")]
    tab = t_cols if mode == "ehr_only" else w_cols
    static = [] if mode == "wearable_only" else list(c.ehr.columns)
    return tab, static


def deep_arrays(c: Cohort, idx: np.ndarray, tab_cols: list[str], static_cols: list[str]) -> tuple[np.ndarray, np.ndarray | None]:
    t = c.table.iloc[idx]
    tab = t[tab_cols].to_numpy(np.float32)
    static = c.ehr.loc[t["patient_id"].to_numpy(), static_cols].to_numpy(np.float32) if static_cols else None
    return tab, static


def predict_rows(model: GBMModel | DeepBundle, c: Cohort, idx: np.ndarray) -> dict[str, np.ndarray | None]:
    """Return spike prob (calibrated), hypo prob (deep only) and P10/P50/P90 glucose (B, 4) in mg/dL."""
    g_now = c.table["g_now"].to_numpy()[idx]
    if isinstance(model, GBMModel):
        X = matrix(c, idx, model.columns)
        out: dict[str, np.ndarray | None] = {"spike": model.predict_proba(X), "hypo": None}
        if model.regressors:
            pts = model.predict_glucose(X, g_now)
            p50 = np.stack([pts[h] for h in HORIZONS], axis=1)
            lo = np.array([model.resid_q[h][0] for h in HORIZONS])
            hi = np.array([model.resid_q[h][1] for h in HORIZONS])
            out.update(p50=p50, p10=p50 + lo, p90=p50 + hi)
        return out
    tab, static = deep_arrays(c, idx, model.tab_cols, model.static_cols)
    seq = windows(c, idx, model.window) if model.model.use_seq else None
    r = model.predict(seq, tab, static)
    q = r["q"] + g_now[:, None, None]
    return {"spike": r["spike"], "hypo": r["hypo"], "p10": q[..., 0], "p50": q[..., 1], "p90": q[..., 2]}
