"""Gradient-boosting baseline (LightGBM) on engineered features, with isotonic calibration."""
from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from common import get_logger

log = get_logger("ml.gbm")
HORIZONS = (30, 60, 90, 120)


@dataclass
class GBMModel:
    """Spike classifier (+ optional per-horizon glucose regressors) for one feature variant."""

    variant: str
    columns: list[str]
    clf: lgb.LGBMClassifier
    calibrator: IsotonicRegression | None = None
    regressors: dict[int, lgb.LGBMRegressor] = field(default_factory=dict)
    resid_q: dict[int, tuple[float, float]] = field(default_factory=dict)  # (P10, P90) residuals on val

    def predict_raw(self, X: pd.DataFrame) -> np.ndarray:
        return self.clf.predict_proba(X[self.columns])[:, 1]

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        p = self.predict_raw(X)
        return self.calibrator.predict(p) if self.calibrator is not None else p

    def predict_glucose(self, X: pd.DataFrame, g_now: np.ndarray) -> dict[int, np.ndarray]:
        """Point forecasts (mg/dL) per horizon; empty if no regressors were trained."""
        return {h: g_now + r.predict(X[self.columns]) for h, r in self.regressors.items()}

    def save(self, path: Path) -> None:
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path: Path) -> "GBMModel":
        with open(path, "rb") as f:
            return pickle.load(f)


def _params(cfg: dict, seed: int) -> dict:
    return dict(
        n_estimators=cfg["n_estimators"], learning_rate=cfg["learning_rate"], num_leaves=cfg["num_leaves"],
        min_child_samples=cfg["min_child_samples"], subsample=cfg["subsample"], subsample_freq=1,
        colsample_bytree=cfg["colsample_bytree"], random_state=seed, n_jobs=4, verbose=-1,
    )


def train_gbm(variant: str, cols: list[str], Xtr: pd.DataFrame, ytr: np.ndarray, Xva: pd.DataFrame,
              yva: np.ndarray, cfg: dict, seed: int, reg_targets: tuple[pd.DataFrame, pd.DataFrame] | None = None) -> GBMModel:
    """Train the classifier with early stopping on validation, then isotonic-calibrate on validation.

    ``reg_targets``: optional (train, val) DataFrames with columns ``d30..d120`` = future glucose minus
    current glucose; trains one L2 regressor per horizon.
    """
    clf = lgb.LGBMClassifier(**_params(cfg, seed))
    clf.fit(Xtr[cols], ytr, eval_set=[(Xva[cols], yva)], eval_metric="average_precision",
            callbacks=[lgb.early_stopping(cfg["early_stopping_rounds"], verbose=False)])
    model = GBMModel(variant, cols, clf)
    raw = model.predict_raw(Xva)
    model.calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw, yva)
    log.info("GBM[%s] best_iter=%s", variant, clf.best_iteration_)

    if reg_targets is not None:
        rtr, rva = reg_targets
        rp = _params({**cfg, "n_estimators": min(cfg["n_estimators"], 300), "learning_rate": 0.08}, seed)
        for h in HORIZONS:
            mtr, mva = rtr[f"d{h}"].notna().to_numpy(), rva[f"d{h}"].notna().to_numpy()
            reg = lgb.LGBMRegressor(**rp)
            reg.fit(Xtr.loc[mtr, cols], rtr.loc[mtr, f"d{h}"], eval_set=[(Xva.loc[mva, cols], rva.loc[mva, f"d{h}"])],
                    callbacks=[lgb.early_stopping(cfg["early_stopping_rounds"], verbose=False)])
            model.regressors[h] = reg
            res = rva.loc[mva, f"d{h}"].to_numpy() - reg.predict(Xva.loc[mva, cols])
            model.resid_q[h] = (float(np.quantile(res, 0.1)), float(np.quantile(res, 0.9)))
    return model
