"""Custom synthetic EHR generator for an Indian / South-Asian Type 2 Diabetes cohort.

Produces two tables:

* ``patients`` - the *observable* EHR (Stream A) the models are allowed to use.
* ``latent``   - hidden "ground truth" lifestyle and physiology traits that drive the world
  simulator (habits, adherence, true physiology). Models never see these columns. They exist so
  the wearable stream is causally linked to the EHR and so tests can check that link.

All distributions are synthetic approximations. Lines marked ``ASSUMPTION`` are collected in
docs/ASSUMPTIONS.md. Nothing here is real patient data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------------------------
# Thresholds (South-Asian specific where relevant)
# ---------------------------------------------------------------------------------------------
SA_BMI_OVERWEIGHT = 23.0  # WHO Asia-Pacific / Indian consensus cut-off
SA_BMI_OBESE = 25.0
SA_WAIST_MALE = 90.0  # cm, Asian Indian abdominal obesity thresholds
SA_WAIST_FEMALE = 80.0

STAPLES = ["rice", "wheat", "millet"]


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def bmi_band(bmi: np.ndarray | float) -> np.ndarray:
    """South-Asian BMI category: normal (<23), overweight (23-25), obese (>=25)."""
    bmi = np.asarray(bmi)
    return np.where(bmi >= SA_BMI_OBESE, "obese", np.where(bmi >= SA_BMI_OVERWEIGHT, "overweight", "normal"))


def ckd_stage(egfr: np.ndarray) -> np.ndarray:
    """KDIGO GFR category from eGFR (mL/min/1.73m2): 1, 2, 3 (3a+3b), 4, 5."""
    return np.select([egfr >= 90, egfr >= 60, egfr >= 30, egfr >= 15], [1, 2, 3, 4], default=5)


def generate_ehr(n: int, rng: np.random.Generator, urban_fraction: float = 0.6) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate ``n`` correlated synthetic T2D patient records.

    Returns ``(patients, latent)`` DataFrames indexed by pseudonymous ``patient_id``.
    """
    # ---- identifiers: pseudonymous, random, no link to any real identifier -------------------
    ids = [f"TWN-{x:06X}" for x in rng.choice(16**6, size=n, replace=False)]

    # ---- demographics ------------------------------------------------------------------------
    sex = np.where(rng.random(n) < 0.55, "M", "F")  # ASSUMPTION: clinic cohorts skew slightly male
    male = sex == "M"
    urban = rng.random(n) < urban_fraction
    age = np.clip(rng.normal(50, 11, n), 25, 80).round()  # ASSUMPTION: Indian T2D clinic age ~50+-11
    family_history = rng.random(n) < 0.55  # ASSUMPTION: high familial clustering in India

    # Genetics: risk-allele counts with approximate South-Asian frequencies (ASSUMPTION, simulated)
    tcf7l2 = rng.binomial(2, 0.30, n)  # rs7903146 T
    slc30a8 = rng.binomial(2, 0.70, n)  # rs13266634 C
    kcnq1 = rng.binomial(2, 0.55, n)  # rs2237892 C
    prs = (
        0.35 * (tcf7l2 - 0.60) + 0.15 * (slc30a8 - 1.40) + 0.20 * (kcnq1 - 1.10)
        + 0.45 * family_history + rng.normal(0, 0.8, n)
    )
    if n >= 30:
        prs = (prs - prs.mean()) / prs.std()  # standardised polygenic risk score
    else:  # tiny cohorts (e.g. one new patient): analytic population mean / SD of the raw score above
        prs = (prs - 0.2475) / 0.878

    # Duration and early onset: higher PRS -> earlier diagnosis (ASSUMPTION)
    duration = np.clip(rng.gamma(2.0, 3.5, n) + 0.8 * np.clip(prs, 0, None), 0.2, 30)
    age_dx = np.maximum(age - duration, 22)
    duration = (age - age_dx).round(1)
    early_onset = age_dx < 40

    # Anthropometrics (South-Asian "thin-fat" phenotype: high waist for a given BMI)
    height_cm = np.where(male, rng.normal(167, 7, n), rng.normal(154, 6, n))
    bmi = np.clip(rng.normal(26.0, 3.8, n) + 1.2 * urban + 0.3 * prs, 18.0, 42.0)
    weight = bmi * (height_cm / 100) ** 2
    waist = np.clip(40 + 2.0 * bmi + 5.0 * male + rng.normal(0, 5, n), 65, 140)

    # ---- diet context ----------------------------------------------------------------------------
    vegetarian = rng.random(n) < 0.35  # ASSUMPTION
    staple_p = np.where(urban[:, None], [[0.45, 0.48, 0.07]], [[0.45, 0.40, 0.15]])
    staple = np.array([rng.choice(STAPLES, p=p) for p in staple_p])

    # ---- latent physiology (hidden) -------------------------------------------------------------
    # Insulin-resistance index (higher = more resistant) and beta-cell function (1 = preserved)
    ir_index = (
        0.10 * (bmi - 25) + 0.03 * (waist - (SA_WAIST_MALE * male + SA_WAIST_FEMALE * ~male))
        + 0.25 * prs + 0.15 * (kcnq1 - 1.1) + rng.normal(0, 0.35, n)
    )
    beta_fn = np.clip(
        1.0 - 0.025 * duration - 0.12 * (tcf7l2 - 0.6) - 0.06 * (slc30a8 - 1.4)
        - 0.10 * early_onset + rng.normal(0, 0.12, n),
        0.15, 1.2,
    )
    adherence = np.clip(rng.beta(8, 2, n), 0.45, 0.99)  # fraction of doses taken (hidden)

    # ---- labs ------------------------------------------------------------------------------------
    # ASSUMPTION: HbA1c driven by resistance, beta-cell loss, adherence; Indian clinic mean ~8.3%
    hba1c = np.clip(
        7.0 + 0.55 * ir_index + 2.2 * (0.85 - beta_fn) + 2.5 * (0.85 - adherence) + rng.normal(0, 0.8, n),
        5.8, 13.5,
    ).round(1)
    fpg = np.clip(26 * hba1c - 62 + rng.normal(0, 14, n), 85, 340).round()
    ppg = np.clip(fpg + 45 + 9 * (hba1c - 7) + rng.normal(0, 18, n), 120, 420).round()

    hdl = np.clip(np.where(male, rng.normal(40, 8, n), rng.normal(46, 9, n)), 22, 80).round()
    tg = np.clip(rng.lognormal(np.log(165), 0.35, n) * (1 + 0.04 * (hba1c - 8)), 60, 600).round()
    ldl = np.clip(rng.normal(108, 30, n), 40, 220).round()
    total_chol = (ldl + hdl + tg / 5).round()

    # Renal: eGFR declines with age, duration, HbA1c (ASSUMPTION)
    egfr = np.clip(
        112 - 0.75 * (age - 40) - 0.7 * duration - 2.0 * (hba1c - 7) + rng.normal(0, 11, n), 15, 130
    ).round()
    creatinine = np.clip(0.95 * (90 / egfr) ** 0.9 * np.where(male, 1.12, 0.92), 0.4, 6).round(2)

    # ---- comorbidities -----------------------------------------------------------------------------
    hypertension = rng.random(n) < _sigmoid(-0.3 + 0.05 * (age - 50) + 0.12 * (bmi - 25) + 0.04 * duration)
    sbp = np.clip(np.where(hypertension, rng.normal(142, 14, n), rng.normal(124, 10, n)), 95, 200).round()
    dbp = np.clip(sbp * 0.62 + rng.normal(0, 6, n), 55, 120).round()
    dyslipidemia = (ldl >= 130) | (tg >= 150) | (hdl < np.where(male, 40, 50))
    prior_cvd = rng.random(n) < _sigmoid(-3.2 + 0.06 * (age - 50) + 0.05 * duration + 0.6 * hypertension + 0.4 * male)
    ckd = ckd_stage(egfr)

    # ---- medications (typical Indian prescribing; ASSUMPTION) ----------------------------------------
    on_metformin = (rng.random(n) < 0.88) & (egfr >= 30)
    metformin_mg = np.where(on_metformin, rng.choice([1000, 1500, 2000], n, p=[0.45, 0.25, 0.30]), 0)
    on_su = rng.random(n) < _sigmoid(-0.6 + 0.4 * (hba1c - 8))
    su_mg = np.where(on_su, rng.choice([1, 2, 4], n, p=[0.4, 0.4, 0.2]), 0)  # glimepiride
    on_dpp4 = rng.random(n) < 0.40
    on_sglt2 = (rng.random(n) < 0.22 + 0.15 * prior_cvd) & (egfr >= 30)
    on_insulin = rng.random(n) < _sigmoid(-2.6 + 0.55 * (hba1c - 8) + 0.12 * duration - 2.0 * (beta_fn - 0.6))
    insulin_type = np.where(on_insulin, np.where(rng.random(n) < 0.55, "premix_30_70", "basal_glargine"), "none")
    u_per_kg = np.where(insulin_type == "premix_30_70", rng.uniform(0.3, 0.6, n), rng.uniform(0.15, 0.35, n))
    insulin_units = np.where(on_insulin, (u_per_kg * weight).round(), 0)

    # ---- hidden lifestyle traits that drive the wearable stream ------------------------------------
    latent = pd.DataFrame(
        {
            "ir_index": ir_index,
            "beta_fn": beta_fn,
            "adherence": adherence,
            "wake_h": np.clip(rng.normal(6.6, 0.6, n), 5.0, 8.5),
            "sleep_need_h": np.clip(rng.normal(7.0, 0.6, n), 5.5, 8.5),
            "sleep_h_mean": np.clip(rng.normal(6.6, 0.7, n), 4.8, 8.3),
            "poor_sleep_prob": np.clip(rng.beta(2, 10, n) + 0.04 * (bmi > 30), 0.02, 0.4),
            "dinner_h": np.clip(rng.normal(20.9, 0.7, n) + 0.3 * urban, 19.0, 22.8),  # late dinners
            "lunch_h": np.clip(rng.normal(13.6, 0.5, n), 12.3, 15.0),
            "snack_prob": np.clip(rng.beta(5, 3, n), 0.2, 0.98),  # evening chai + snack
            "sweet_prob": np.clip(rng.beta(1.5, 10, n), 0.0, 0.4),
            "portion": np.clip(rng.normal(1.0, 0.1, n) + 0.08 * male + 0.01 * (bmi - 25), 0.75, 1.35),
            "walk_habit": rng.random(n) < np.where(urban, 0.40, 0.30),
            "post_dinner_walk": rng.random(n) < 0.25,
            "base_activity": np.clip(rng.normal(np.where(urban, 0.6, 1.0), 0.2, n), 0.2, 1.6),  # rural labour
            "stress_prob": np.clip(rng.beta(2, 5, n) * np.where(urban, 1.3, 0.8), 0.02, 0.8),
            "meal_log_prob": np.clip(rng.beta(6, 2, n), 0.35, 0.98),
            "rest_hr": np.clip(rng.normal(74, 7, n) + 0.3 * (bmi - 25) - 3 * (~urban), 55, 95),
            "hrv_base": np.clip(42 - 0.45 * (age - 40) - 0.5 * duration + rng.normal(0, 6, n), 9, 70),
        },
        index=pd.Index(ids, name="patient_id"),
    )

    patients = pd.DataFrame(
        {
            "age": age.astype(int),
            "sex": sex,
            "region": np.where(urban, "urban", "rural"),
            "height_cm": height_cm.round(1),
            "weight_kg": weight.round(1),
            "bmi": bmi.round(1),
            "bmi_band_sa": bmi_band(bmi),
            "waist_cm": waist.round(1),
            "waist_high_sa": waist >= np.where(male, SA_WAIST_MALE, SA_WAIST_FEMALE),
            "family_history_dm": family_history,
            "years_since_dx": duration,
            "age_at_dx": age_dx.round(1),
            "early_onset": early_onset,
            "hypertension": hypertension,
            "sbp": sbp,
            "dbp": dbp,
            "dyslipidemia": dyslipidemia,
            "ckd_stage": ckd,
            "prior_cvd": prior_cvd,
            "hba1c": hba1c,
            "fasting_glucose": fpg,
            "postprandial_glucose": ppg,
            "total_chol": total_chol,
            "ldl": ldl,
            "hdl": hdl,
            "triglycerides": tg,
            "egfr": egfr,
            "creatinine": creatinine,
            "metformin_mg": metformin_mg.astype(int),
            "sulfonylurea_mg": su_mg.astype(int),
            "dpp4": on_dpp4,
            "sglt2": on_sglt2,
            "insulin_type": insulin_type,
            "insulin_units_day": insulin_units.astype(int),
            "snp_tcf7l2": tcf7l2,
            "snp_slc30a8": slc30a8,
            "snp_kcnq1": kcnq1,
            "prs": prs.round(3),
            "diet": np.where(vegetarian, "vegetarian", "non_vegetarian"),
            "staple": staple,
            "consent_twin_monitoring": True,  # simulated consent (DPDP Act s.6 style)
        },
        index=pd.Index(ids, name="patient_id"),
    )
    return patients, latent


# Columns of the EHR used as model inputs (numeric / one-hot encoded by ml.features)
EHR_NUMERIC = [
    "age", "bmi", "waist_cm", "years_since_dx", "age_at_dx", "sbp", "dbp", "hba1c", "fasting_glucose",
    "postprandial_glucose", "total_chol", "ldl", "hdl", "triglycerides", "egfr", "creatinine",
    "metformin_mg", "sulfonylurea_mg", "insulin_units_day", "snp_tcf7l2", "snp_slc30a8", "snp_kcnq1",
    "prs", "ckd_stage",
]
EHR_BOOL = [
    "family_history_dm", "early_onset", "hypertension", "dyslipidemia", "prior_cvd", "dpp4", "sglt2",
    "waist_high_sa",
]
EHR_CATEGORICAL = {
    "sex": ["M", "F"],
    "region": ["urban", "rural"],
    "insulin_type": ["none", "basal_glargine", "premix_30_70"],
    "diet": ["vegetarian", "non_vegetarian"],
    "staple": STAPLES,
    "bmi_band_sa": ["normal", "overweight", "obese"],
}


def ehr_feature_matrix(patients: pd.DataFrame) -> pd.DataFrame:
    """Encode the observable EHR into a numeric feature matrix (one row per patient)."""
    out = patients[EHR_NUMERIC].astype(float).copy()
    for c in EHR_BOOL:
        out[c] = patients[c].astype(float)
    for c, levels in EHR_CATEGORICAL.items():
        for lv in levels:
            out[f"{c}={lv}"] = (patients[c] == lv).astype(float)
    return out.add_prefix("ehr_")
