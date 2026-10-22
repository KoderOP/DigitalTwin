"""Serving-time predictor: turns a twin's live buffer into risk, forecast and explanation."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from common import get_logger, path_of
from ml.alerting import alert_level
from ml.deep import DeepBundle
from ml.explain import group_attributions, integrated_gradients, tree_shap_fn
from ml.features import seq_channels, wearable_features
from ml.gbm import HORIZONS, GBMModel

log = get_logger("twin.predictor")


def time_to_threshold(g_now: float, traj: list[float], thr: float = 180.0) -> int | None:
    """Minutes until a piecewise-linear trajectory (0, 30, 60, 90, 120 min) first exceeds ``thr``."""
    pts = [(0, g_now)] + [(h, v) for h, v in zip(HORIZONS, traj)]
    for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
        if v0 <= thr < v1:
            return int(round(t0 + (thr - v0) / (v1 - v0) * (t1 - t0)))
    return None


class Predictor:
    """Loads the trained fused models and the alert policy chosen during evaluation."""

    def __init__(self, art_dir: Path | None = None, model: str | None = None) -> None:
        art = art_dir or path_of("artifacts_dir")
        serving = json.loads((art / "serving.json").read_text())
        self.kind = model or serving["model"]
        self.thresholds = serving["thresholds"][f"{self.kind}_fused"]
        self.refractory_min = serving.get("refractory_min", 60)
        self.notify_level = serving.get("notify_level", "RED")
        self.deep = DeepBundle.load(art / "deep_fused.pt")
        self.gbm = GBMModel.load(art / "gbm_fused.pkl")
        self._shap = None
        log.info("Serving %s_fused (thresholds %s)", self.kind, self.thresholds)

    @property
    def model_name(self) -> str:
        return f"{self.kind}_fused"

    def predict_many(self, frame: pd.DataFrame, ehr_encoded: pd.Series, last_n: int) -> list[dict]:
        """Batched predictions for the last ``last_n`` rows of a frame (used to back-fill history)."""
        feats = wearable_features(frame)
        rows = np.arange(max(len(frame) - last_n, 0), len(frame))
        g_now = feats["w_g_now"].to_numpy()[rows]
        if self.kind == "deep":
            b = self.deep
            seq = seq_channels(frame)
            pad = np.concatenate([np.repeat(seq[:1], b.window, axis=0), seq])
            win = np.stack([pad[r + 1 : r + 1 + b.window] for r in rows])
            tab = feats.iloc[rows][b.tab_cols].to_numpy(np.float32)
            static = np.repeat(ehr_encoded[b.static_cols].to_numpy(np.float32)[None], len(rows), axis=0)
            r = b.predict(win, tab, static)
            risk, q = r["spike"], r["q"][:, 1, :] + g_now[:, None]
        else:
            m = self.gbm
            X = pd.concat([feats.iloc[rows].reset_index(drop=True),
                           pd.DataFrame([ehr_encoded.to_dict()] * len(rows))], axis=1)[m.columns]
            risk = m.predict_proba(X)
            p50 = g_now + m.regressors[60].predict(X)
            q = np.stack([p50 + m.resid_q[60][0], p50, p50 + m.resid_q[60][1]], axis=1)
        out = []
        for k, r_ in enumerate(rows):
            elig = g_now[k] <= 180
            out.append({"ts": pd.Timestamp(frame["ts"].iloc[r_]).isoformat(), "risk": round(float(risk[k]), 4) if elig else None,
                        "level": alert_level(float(risk[k]), self.thresholds) if elig else "HIGH",
                        "p10_60": round(float(q[k, 0]), 1), "p50_60": round(float(q[k, 1]), 1), "p90_60": round(float(q[k, 2]), 1)})
        return out

    def predict(self, frame: pd.DataFrame, ehr_encoded: pd.Series, ehr_raw: dict, explain: bool = False) -> dict:
        feats = wearable_features(frame)
        last = feats.iloc[-1]
        g_now = float(last["w_g_now"])
        if self.kind == "deep":
            b = self.deep
            seq = seq_channels(frame)[-b.window:]
            if len(seq) < b.window:  # pad at the start when the buffer is short
                seq = np.concatenate([np.repeat(seq[:1], b.window - len(seq), axis=0), seq])
            tab = last[b.tab_cols].to_numpy(np.float32)[None]
            static = ehr_encoded[b.static_cols].to_numpy(np.float32)[None]
            r = b.predict(seq[None], tab, static)
            risk = float(r["spike"][0])
            hypo = float(r["hypo"][0])
            q = r["q"][0] + g_now
            p10, p50, p90 = q[:, 0], q[:, 1], q[:, 2]
            attr = integrated_gradients(b, seq[None], tab, static) if explain else None
        else:
            m = self.gbm
            X = pd.DataFrame([{**last.to_dict(), **ehr_encoded.to_dict()}])[m.columns]
            risk = float(m.predict_proba(X)[0])
            hypo = None
            pts = m.predict_glucose(X, np.array([g_now]))
            p50 = np.array([pts[h][0] for h in HORIZONS])
            p10 = p50 + np.array([m.resid_q[h][0] for h in HORIZONS])
            p90 = p50 + np.array([m.resid_q[h][1] for h in HORIZONS])
            if explain:
                self._shap = self._shap or tree_shap_fn(m)
                attr = self._shap(X)
            else:
                attr = None

        eligible = g_now <= 180
        level = alert_level(risk, self.thresholds) if eligible else ("HIGH" if g_now > 180 else "GREEN")
        ttt = time_to_threshold(g_now, list(p50))
        ttt_possible = time_to_threshold(g_now, list(p90))
        out = {
            "model": self.model_name, "risk": round(risk, 4), "level": level, "eligible": bool(eligible),
            "g_now": round(g_now, 1), "hypo_risk": None if hypo is None else round(hypo, 4),
            "forecast": [{"minutes": h, "p10": round(float(a), 1), "p50": round(float(b_), 1), "p90": round(float(c), 1)}
                         for h, a, b_, c in zip(HORIZONS, p10, p50, p90)],
            "minutes_to_spike": ttt if ttt is not None else (ttt_possible if level in ("AMBER", "RED") else None),
            "minutes_to_spike_basis": "median forecast" if ttt is not None else ("upper (P90) forecast" if ttt_possible is not None and level in ("AMBER", "RED") else None),
            "thresholds": self.thresholds,
            "features": {k: (None if pd.isna(v) else round(float(v), 3)) for k, v in last.items()},
        }
        if attr is not None:
            out["explanation"] = group_attributions(attr, out["features"], ehr_raw)
        return out
