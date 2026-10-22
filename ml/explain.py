"""Explainability: feature attributions -> grouped, plain-language factors.

* GBM: exact TreeSHAP (log-odds space) via ``shap.TreeExplainer``.
* Deep: Integrated Gradients on the spike logit (an Aumann-Shapley value, so it belongs to the SHAP
  family), with a training-mean baseline. Sequence attributions are summed over time per channel.

Attributions are aggregated into clinical *factors* (e.g. "Recent meal", "Sleep last night") and
each factor gets a sentence built from the patient's current values.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
import torch

from ml.deep import DeepBundle
from ml.features import SEQ_CHANNELS

# factor -> (prefixes/names that belong to it)
FACTORS: list[tuple[str, tuple[str, ...]]] = [
    ("data_quality", ("w_valid_", "w_g_age_min", "w_wear_missing", "seq_cgm_missing", "seq_wear_missing")),
    ("glucose_trend", ("w_g_now", "w_slope_", "w_accel_", "seq_cgm", "w_g_mean_1h", "w_g_max_1h", "w_g_min_1h", "w_g_std_1h")),
    ("recent_meal", ("w_min_since_meal", "w_min_since_bigmeal", "w_last_meal_carbs", "w_carbs_", "w_cob", "w_meals_24h", "seq_carbs")),
    ("habitual_pattern", ("w_yday_", "w_2day_")),
    ("glycemic_control", ("ehr_hba1c", "ehr_fasting_glucose", "ehr_postprandial_glucose", "w_g_mean_24h", "w_g_mean_6h",
                          "w_g_mean_3h", "w_tar_24h", "w_g_max_", "w_g_min_", "w_g_std_", "w_cv_24h", "w_tbr_24h")),
    ("sleep", ("w_sleep_", "w_deep_h", "w_rem_h", "w_asleep_now", "w_min_since_wake", "w_hrv_night", "seq_asleep", "seq_deep", "seq_rem", "w_spo2")),
    ("activity", ("w_steps_", "w_active_min", "w_min_since_walk", "seq_steps", "seq_activity")),
    ("medication", ("ehr_metformin", "ehr_sulfonylurea", "ehr_insulin", "ehr_dpp4", "ehr_sglt2", "w_min_since_met", "w_met_24h",
                    "w_min_since_su", "w_ins_12h", "w_iob", "w_meds_24h", "seq_med", "seq_ins")),
    ("stress_autonomic", ("w_hr_", "w_hrv_1h", "w_hrv_z", "seq_hr", "seq_hrv", "w_skin_temp")),
    ("time_of_day", ("t_", "seq_tod")),
    ("body_composition", ("ehr_bmi", "ehr_waist", "ehr_weight")),
    ("genetics_family", ("ehr_snp", "ehr_prs", "ehr_family", "ehr_early_onset")),
    ("diet_pattern", ("ehr_diet", "ehr_staple")),
    ("comorbidity_duration", ("ehr_years_since_dx", "ehr_age", "ehr_ckd", "ehr_egfr", "ehr_creat", "ehr_hypert", "ehr_sbp", "ehr_dbp",
                              "ehr_dyslip", "ehr_ldl", "ehr_hdl", "ehr_trig", "ehr_total_chol", "ehr_prior_cvd", "ehr_sex", "ehr_region")),
]
TITLES = {
    "glucose_trend": "Current glucose & trend", "recent_meal": "Recent meal / carbs", "habitual_pattern": "Usual pattern at this time",
    "glycemic_control": "Overall glycemic control", "sleep": "Sleep last night", "activity": "Physical activity",
    "medication": "Medication", "stress_autonomic": "Stress / heart-rate variability", "time_of_day": "Time of day",
    "body_composition": "Body composition", "genetics_family": "Genetic / family risk", "diet_pattern": "Diet pattern",
    "comorbidity_duration": "Diabetes duration & comorbidities", "data_quality": "Sensor data quality",
}
SOURCE = {k: ("EHR" if k in ("body_composition", "genetics_family", "diet_pattern", "comorbidity_duration") else "wearable")
          for k in TITLES}
SOURCE.update({"glycemic_control": "EHR + CGM", "medication": "EHR + app", "time_of_day": "context"})


def factor_of(name: str) -> str:
    for fac, keys in FACTORS:
        if any(name.startswith(k) for k in keys):
            return fac
    return "comorbidity_duration" if name.startswith("ehr_") else "glucose_trend"


def _fmt_clock(minutes_ago: float) -> str:
    return f"{int(minutes_ago // 60)} h {int(minutes_ago % 60)} min ago" if minutes_ago >= 60 else f"{int(minutes_ago)} min ago"


def describe(factor: str, v: dict[str, float], ehr: dict) -> str:
    """Plain-language description of a factor given current feature values ``v`` and EHR fields."""
    g = lambda k, d=float("nan"): float(v.get(k, d)) if v.get(k) is not None else d  # noqa: E731
    try:
        if factor == "glucose_trend":
            s = g("w_slope_30m", 0)
            arrow = "rising" if s > 0.5 else "falling" if s < -0.5 else "stable"
            return f"Glucose {g('w_g_now'):.0f} mg/dL, {arrow} ({s:+.1f} mg/dL/min over 30 min)"
        if factor == "recent_meal":
            m = g("w_min_since_meal", 720)
            if m >= 720:
                return "No meal logged in the last 12 h"
            big = " (high-carb)" if g("w_last_meal_carbs", 0) >= 60 else ""
            return f"Last logged meal {g('w_last_meal_carbs', 0):.0f} g carbs{big}, {_fmt_clock(m)}; {g('w_carbs_3h', 0):.0f} g in last 3 h"
        if factor == "habitual_pattern":
            return f"Yesterday at this time glucose peaked at {g('w_yday_next2h_max'):.0f} mg/dL within 2 h"
        if factor == "glycemic_control":
            return f"HbA1c {ehr.get('hba1c', float('nan')):.1f}%; 24 h mean {g('w_g_mean_24h'):.0f} mg/dL, {100 * g('w_tar_24h', 0):.0f}% time above 180"
        if factor == "sleep":
            h = g("w_sleep_h_24h", 0)
            q = "poor" if h < 5.5 else "short" if h < 6.5 else "adequate"
            return f"Slept {h:.1f} h in the last 24 h ({q}; sleep debt {g('w_sleep_debt_h', 0):.1f} h)"
        if factor == "activity":
            return f"{g('w_steps_3h', 0):.0f} steps in last 3 h; {g('w_active_min_3h', 0):.0f} active min"
        if factor == "medication":
            meds = []
            if ehr.get("metformin_mg"):
                ms = g("w_min_since_met", 1440)
                meds.append("metformin " + ("not logged in 24 h" if ms >= 1440 else f"taken {_fmt_clock(ms)}"))
            if ehr.get("insulin_type", "none") != "none":
                meds.append(f"{g('w_ins_12h', 0):.0f} U insulin in last 12 h")
            if ehr.get("sulfonylurea_mg"):
                meds.append("on sulfonylurea")
            return "; ".join(meds) if meds else "No glucose-lowering medication logged"
        if factor == "stress_autonomic":
            z = g("w_hrv_z", 0)
            state = "low HRV (possible stress)" if z < -0.8 else "HRV normal for this patient"
            return f"HR {g('w_hr_1h'):.0f} bpm, HRV {g('w_hrv_1h'):.0f} ms, {state}"
        if factor == "time_of_day":
            return "Time of day: the patient usually eats around now"
        if factor == "body_composition":
            return f"BMI {ehr.get('bmi', 0):.1f} ({ehr.get('bmi_band_sa', '')}, South-Asian cut-offs), waist {ehr.get('waist_cm', 0):.0f} cm"
        if factor == "genetics_family":
            return f"Polygenic risk z={ehr.get('prs', 0):+.1f}; TCF7L2 risk alleles {ehr.get('snp_tcf7l2', 0)}; family history {'yes' if ehr.get('family_history_dm') else 'no'}"
        if factor == "diet_pattern":
            return f"{str(ehr.get('diet', '')).replace('_', '-').capitalize()} diet, staple {ehr.get('staple', '')}"
        if factor == "comorbidity_duration":
            return f"T2D for {ehr.get('years_since_dx', 0):.0f} y; eGFR {ehr.get('egfr', 0):.0f}; {'hypertension' if ehr.get('hypertension') else 'no hypertension'}"
        if factor == "data_quality":
            return f"CGM coverage last hour {100 * g('w_valid_1h', 1):.0f}%"
    except (TypeError, ValueError):
        pass
    return TITLES.get(factor, factor)


def group_attributions(attr: dict[str, float], values: dict[str, float], ehr: dict, top: int = 5) -> list[dict]:
    """Sum per-feature attributions into factors, rank by |contribution| and describe the top ones."""
    agg: dict[str, float] = {}
    for k, a in attr.items():
        f = factor_of(k)
        agg[f] = agg.get(f, 0.0) + float(a)
    ranked = sorted(agg.items(), key=lambda kv: -abs(kv[1]))[:top]
    total = sum(abs(a) for a in agg.values()) or 1.0
    return [{"factor": f, "title": TITLES.get(f, f), "source": SOURCE.get(f, ""), "contribution": round(a, 4),
             "share": round(abs(a) / total, 3), "direction": "increases" if a > 0 else "decreases",
             "text": describe(f, values, ehr)} for f, a in ranked]


def integrated_gradients(bundle: DeepBundle, seq: np.ndarray | None, tab: np.ndarray, static: np.ndarray | None,
                         steps: int = 24) -> dict[str, float]:
    """IG attributions for one sample (spike logit). Inputs are raw (un-normalised, batch of 1)."""
    model = bundle.model
    model.eval()
    t, s = bundle.prep(tab, static)
    alphas = torch.linspace(1.0 / steps, 1.0, steps).view(-1, 1)
    tab_x = torch.from_numpy(t)
    tab_in = (alphas * tab_x).requires_grad_(True)  # baseline 0 == training mean after standardisation
    st_in = None
    if s is not None:
        st_x = torch.from_numpy(s)
        st_in = (alphas * st_x).requires_grad_(True)
    seq_in = None
    if seq is not None and model.use_seq:
        sx = torch.from_numpy(seq)  # (1,T,C)
        base = torch.from_numpy(bundle.seq_mean.astype(np.float32)).view(1, 1, -1).expand_as(sx)
        seq_in = (base + alphas.view(-1, 1, 1) * (sx - base)).requires_grad_(True)
    out = model(seq_in, tab_in, st_in)["spike"].sum()
    out.backward()
    attr: dict[str, float] = {}
    a_tab = (tab_in.grad.mean(0) * tab_x[0]).numpy()
    for k, name in enumerate(bundle.tab_cols):
        attr[name] = float(a_tab[k])
    if st_in is not None:
        a_st = (st_in.grad.mean(0) * st_x[0]).numpy()
        for k, name in enumerate(bundle.static_cols):
            attr[name] = float(a_st[k])
    if seq_in is not None:
        a_seq = (seq_in.grad.mean(0) * (sx[0] - base[0])).sum(0).numpy()
        for k, name in enumerate(SEQ_CHANNELS):
            attr[f"seq_{name}"] = float(a_seq[k])
    return attr


def tree_shap_fn(model) -> Callable[[object], dict[str, float]]:
    """Return a function mapping a 1-row DataFrame to TreeSHAP values (log-odds) per feature."""
    import shap

    explainer = shap.TreeExplainer(model.clf)

    def fn(X) -> dict[str, float]:
        sv = explainer.shap_values(X[model.columns])
        sv = sv[1] if isinstance(sv, list) else sv
        return {c: float(v) for c, v in zip(model.columns, np.asarray(sv)[0])}

    return fn
