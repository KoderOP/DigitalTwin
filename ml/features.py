"""Causal feature engineering over a patient's 5-minute wearable frame.

Every feature at row t uses only rows <= t (rolling windows look backwards; the "yesterday" features
look at t-24h..t-22h, which is in the past). The same functions run on the training data and on the
live twin buffer, so training and serving features cannot drift apart.

Feature groups (prefixes are used for the ablation study):
    w_*  wearable / CGM / app stream (Stream B)
    t_*  clock context (time of day, weekend), shared by all variants
    ehr_* static EHR (Stream A), see data_gen.ehr_generator.ehr_feature_matrix
"""
from __future__ import annotations

import numpy as np
import pandas as pd

STEP_MIN = 5
H = 60 // STEP_MIN  # rows per hour

FRAME_COLUMNS = [
    "ts", "cgm", "hr", "hrv_rmssd", "steps", "activity", "sleep_stage", "spo2", "skin_temp",
    "carbs", "med_met", "med_su", "med_dpp4", "med_sglt2", "ins_units",
]
EVENT_CHANNEL = {
    "metformin": "med_met", "sulfonylurea": "med_su", "dpp4": "med_dpp4", "sglt2": "med_sglt2",
    "insulin_premix": "ins_units", "insulin_basal": "ins_units",
}

# Deep-model sequence channels (order matters; see seq_channels)
SEQ_CHANNELS = [
    "cgm", "cgm_missing", "steps", "activity", "hr", "hrv", "wear_missing", "asleep", "deep", "rem",
    "carbs", "med_met", "med_su", "med_tab", "ins_units", "tod_sin", "tod_cos",
]


def build_frame(wear_p: pd.DataFrame, events_p: pd.DataFrame | None) -> pd.DataFrame:
    """Combine one patient's wearable rows with logged events aggregated onto the 5-min grid.

    The record at ``ts`` covers the interval (ts-5min, ts]; an event at minute m is assigned to the
    first record with ts > m.
    """
    df = wear_p[["ts", "cgm", "hr", "hrv_rmssd", "steps", "activity", "sleep_stage", "spo2", "skin_temp"]].copy()
    df = df.sort_values("ts").reset_index(drop=True)
    for c in ("carbs", "med_met", "med_su", "med_dpp4", "med_sglt2", "ins_units"):
        df[c] = 0.0
    if events_p is not None and len(events_p):
        t0 = df["ts"].iloc[0] - pd.Timedelta(minutes=STEP_MIN)
        k = ((events_p["ts"] - t0) / pd.Timedelta(minutes=STEP_MIN)).astype(int).to_numpy()
        ok = (k >= 0) & (k < len(df))
        ev = events_p[ok]
        k = k[ok]
        for (typ, name, amt), kk in zip(ev[["type", "name", "logged_amount"]].itertuples(index=False), k):
            if typ == "meal":
                df.at[kk, "carbs"] += float(amt)
            elif name in EVENT_CHANNEL:
                df.at[kk, EVENT_CHANNEL[name]] += float(amt)
    return df


def _since(mask: np.ndarray, cap: float) -> np.ndarray:
    """Minutes since the last True in ``mask`` (capped)."""
    idx = np.where(mask, np.arange(len(mask)), -10**9)
    last = np.maximum.accumulate(idx)
    out = (np.arange(len(mask)) - last) * STEP_MIN
    return np.minimum(out, cap).astype(float)


def _decay_sum(x: np.ndarray, tau_min: float) -> np.ndarray:
    """Exponentially-decayed running sum (e.g. carbs-on-board proxy)."""
    a = np.exp(-STEP_MIN / tau_min)
    out = np.empty(len(x))
    acc = 0.0
    for i, v in enumerate(x):
        acc = acc * a + v
        out[i] = acc
    return out


def impute_cgm(cgm: pd.Series, limit: int = 12) -> tuple[pd.Series, pd.Series]:
    """Causal imputation: forward-fill up to ``limit`` readings (1 h), then the trailing 24 h mean.

    Returns (imputed, minutes since last valid reading).
    """
    ff = cgm.ffill(limit=limit)
    mean24 = cgm.rolling(24 * H, min_periods=1).mean()
    imp = ff.fillna(mean24).fillna(150.0)
    age = pd.Series(_since(cgm.notna().to_numpy(), 24 * 60), index=cgm.index)
    return imp, age


def wearable_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute w_* and t_* features for every row of a patient frame (see module doc)."""
    f: dict[str, np.ndarray | pd.Series] = {}
    g = df["cgm"].astype(float)
    gi, age = impute_cgm(g)
    f["w_g_now"] = gi
    f["w_g_age_min"] = age
    for lag in (3, 6, 12):
        f[f"w_slope_{lag*5}m"] = (gi - gi.shift(lag)) / (lag * STEP_MIN)
    f["w_accel_15m"] = f["w_slope_15m"] - f["w_slope_15m"].shift(3)
    for name, win in (("1h", H), ("3h", 3 * H), ("6h", 6 * H), ("24h", 24 * H)):
        r = g.rolling(win, min_periods=max(win // 4, 2))
        f[f"w_g_mean_{name}"] = r.mean()
        f[f"w_g_std_{name}"] = r.std()
        f[f"w_g_max_{name}"] = r.max()
        f[f"w_g_min_{name}"] = r.min()
    f["w_cv_24h"] = f["w_g_std_24h"] / f["w_g_mean_24h"]
    valid = g.notna()
    for name, win in (("24h", 24 * H),):
        f[f"w_tar_{name}"] = (g > 180).rolling(win, min_periods=1).sum() / valid.rolling(win, min_periods=1).sum().clip(lower=1)
        f[f"w_tbr_{name}"] = (g < 70).rolling(win, min_periods=1).sum() / valid.rolling(win, min_periods=1).sum().clip(lower=1)
    f["w_valid_1h"] = valid.rolling(H, min_periods=1).mean()
    f["w_valid_6h"] = valid.rolling(6 * H, min_periods=1).mean()
    # habitual pattern: what happened over the next 2 h at the same time yesterday (already past)
    fut2h_max = g[::-1].rolling(2 * H, min_periods=1).max()[::-1]
    fut2h_mean = g[::-1].rolling(2 * H, min_periods=1).mean()[::-1]
    f["w_yday_next2h_max"] = fut2h_max.shift(24 * H)
    f["w_yday_next2h_mean"] = fut2h_mean.shift(24 * H)
    f["w_yday_g"] = g.shift(24 * H)
    f["w_2day_next2h_max"] = fut2h_max.shift(48 * H)

    # meals (logged)
    carbs = df["carbs"].to_numpy(float)
    meal = carbs > 0
    f["w_min_since_meal"] = _since(meal, 720)
    f["w_min_since_bigmeal"] = _since(carbs >= 50, 720)
    last_carbs = pd.Series(np.where(meal, carbs, np.nan)).ffill().fillna(0).to_numpy()
    f["w_last_meal_carbs"] = np.where(f["w_min_since_meal"] < 720, last_carbs, 0.0)
    cs = pd.Series(carbs)
    for name, win in (("1h", H), ("3h", 3 * H), ("6h", 6 * H), ("24h", 24 * H)):
        f[f"w_carbs_{name}"] = cs.rolling(win, min_periods=1).sum().to_numpy()
    f["w_cob"] = _decay_sum(carbs, 60.0)
    f["w_meals_24h"] = pd.Series(meal.astype(float)).rolling(24 * H, min_periods=1).sum().to_numpy()

    # medication intake logs (smart pill box / connected pen)
    f["w_min_since_met"] = _since(df["med_met"].to_numpy() > 0, 1440)
    f["w_met_24h"] = df["med_met"].rolling(24 * H, min_periods=1).sum().to_numpy()
    f["w_min_since_su"] = _since(df["med_su"].to_numpy() > 0, 1440)
    f["w_ins_12h"] = df["ins_units"].rolling(12 * H, min_periods=1).sum().to_numpy()
    f["w_iob"] = _decay_sum(df["ins_units"].to_numpy(float), 240.0)
    f["w_meds_24h"] = (df[["med_met", "med_su", "med_dpp4", "med_sglt2", "ins_units"]] > 0).sum(axis=1).rolling(24 * H, min_periods=1).sum().to_numpy()

    # activity
    steps = df["steps"].fillna(0)
    for name, win in (("30m", 6), ("1h", H), ("3h", 3 * H), ("24h", 24 * H)):
        f[f"w_steps_{name}"] = steps.rolling(win, min_periods=1).sum().to_numpy()
    act = df["activity"].fillna(0)
    f["w_active_min_3h"] = (act >= 0.3).rolling(3 * H, min_periods=1).sum().to_numpy() * STEP_MIN
    f["w_min_since_walk"] = _since(act.to_numpy() >= 0.3, 1440)

    # heart rate / HRV
    hr, hrv = df["hr"], df["hrv_rmssd"]
    f["w_hr_30m"] = hr.rolling(6, min_periods=1).mean()
    f["w_hr_1h"] = hr.rolling(H, min_periods=1).mean()
    f["w_hr_rel_24h"] = f["w_hr_1h"] - hr.rolling(24 * H, min_periods=H).mean()
    f["w_hrv_1h"] = hrv.rolling(H, min_periods=1).mean()
    hrv24 = hrv.rolling(24 * H, min_periods=H)
    f["w_hrv_z"] = (f["w_hrv_1h"] - hrv24.mean()) / hrv24.std().clip(lower=1)
    f["w_wear_missing_1h"] = hr.isna().rolling(H, min_periods=1).mean()

    # sleep (last 12 h ~ last night when evaluated during the day)
    st = df["sleep_stage"].fillna(0).astype(int)
    asleep = (st > 0).astype(float)
    f["w_sleep_h_12h"] = asleep.rolling(12 * H, min_periods=1).sum().to_numpy() * STEP_MIN / 60
    f["w_deep_h_12h"] = (st == 2).astype(float).rolling(12 * H, min_periods=1).sum().to_numpy() * STEP_MIN / 60
    f["w_rem_h_12h"] = (st == 3).astype(float).rolling(12 * H, min_periods=1).sum().to_numpy() * STEP_MIN / 60
    f["w_sleep_h_24h"] = asleep.rolling(24 * H, min_periods=1).sum().to_numpy() * STEP_MIN / 60
    f["w_sleep_debt_h"] = np.clip(7.0 - f["w_sleep_h_24h"], 0, None)
    f["w_asleep_now"] = asleep.to_numpy()
    f["w_min_since_wake"] = _since(asleep.to_numpy() > 0, 1440)
    night_hrv = hrv.where(asleep > 0)
    f["w_hrv_night"] = night_hrv.rolling(12 * H, min_periods=1).mean()
    f["w_spo2_min_12h"] = df["spo2"].rolling(12 * H, min_periods=1).min()
    f["w_skin_temp_1h"] = df["skin_temp"].rolling(H, min_periods=1).mean()

    # clock context
    ts = pd.to_datetime(df["ts"])
    mod = (ts.dt.hour * 60 + ts.dt.minute).to_numpy()
    f["t_tod_sin"] = np.sin(2 * np.pi * mod / 1440)
    f["t_tod_cos"] = np.cos(2 * np.pi * mod / 1440)
    f["t_weekend"] = (ts.dt.dayofweek >= 5).astype(float).to_numpy()

    out = pd.DataFrame({k: np.asarray(v, dtype=np.float32) for k, v in f.items()}, index=df.index)
    return out


def seq_channels(df: pd.DataFrame) -> np.ndarray:
    """Normalised per-step channels for the deep temporal encoder, shape (T, len(SEQ_CHANNELS))."""
    g = df["cgm"].astype(float)
    gi, _ = impute_cgm(g)
    hr = df["hr"].astype(float)
    hrv = df["hrv_rmssd"].astype(float)
    st = df["sleep_stage"].fillna(0).astype(int).to_numpy()
    ts = pd.to_datetime(df["ts"])
    mod = (ts.dt.hour * 60 + ts.dt.minute).to_numpy()
    cols = [
        (gi.to_numpy() - 150) / 50,
        g.isna().to_numpy(float),
        df["steps"].fillna(0).to_numpy(float) / 200,
        df["activity"].fillna(0).to_numpy(float),
        ((hr.ffill(limit=24).fillna(75)) - 75).to_numpy() / 12,
        (np.log(hrv.ffill(limit=24).fillna(30).clip(lower=5)) - 3.4).to_numpy() / 0.35,
        hr.isna().to_numpy(float),
        (st > 0).astype(float),
        (st == 2).astype(float),
        (st == 3).astype(float),
        df["carbs"].to_numpy(float) / 50,
        df["med_met"].to_numpy(float),
        df["med_su"].to_numpy(float) / 2,
        (df["med_dpp4"] + df["med_sglt2"]).to_numpy(float),
        df["ins_units"].to_numpy(float) / 20,
        np.sin(2 * np.pi * mod / 1440),
        np.cos(2 * np.pi * mod / 1440),
    ]
    return np.stack(cols, axis=1).astype(np.float32)


def labels(df: pd.DataFrame, horizon: int = 24, spike: float = 180, hypo: float = 70) -> pd.DataFrame:
    """Prediction targets at every row (NaN where the future is insufficiently observed).

    * ``eligible``: current CGM (imputed, last real reading <= 15 min old) <= spike threshold.
    * ``y_spike``: two consecutive CGM readings > 180 within the next ``horizon`` steps (120 min).
    * ``y_hypo``: two consecutive readings < 70 within the horizon.
    * ``y_g{30,60,90,120}``: CGM at the horizon (NaN if missing).
    """
    g = df["cgm"].astype(float)
    gi, age = impute_cgm(g)
    hi = ((g > spike) & (g.shift(-1) > spike)).astype(float)
    lo = ((g < hypo) & (g.shift(-1) < hypo)).astype(float)
    fut_valid = g.notna().astype(float)[::-1].rolling(horizon, min_periods=1).sum()[::-1].shift(-1)
    fut_hi = hi[::-1].rolling(horizon, min_periods=1).max()[::-1].shift(-1)
    fut_lo = lo[::-1].rolling(horizon, min_periods=1).max()[::-1].shift(-1)
    enough = fut_valid >= horizon // 2
    out = pd.DataFrame(index=df.index)
    out["eligible"] = (gi <= spike) & (age <= 15)
    out["y_spike"] = fut_hi.where(enough)
    out["y_hypo"] = fut_lo.where(enough)
    for h in (6, 12, 18, 24):
        out[f"y_g{h*5}"] = g.shift(-h)
    out["g_now"] = gi
    return out
