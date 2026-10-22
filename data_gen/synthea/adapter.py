"""Convert a Synthea CSV export into the twin's EHR schema (see README.md).

Synthea supplies demographics, conditions, labs and medications. India-specific context and genetic
markers that Synthea does not model are imputed from the custom generator's priors and flagged.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from data_gen.ehr_generator import bmi_band, ckd_stage, generate_ehr

T2D = "44054006"
CONDITIONS = {"hypertension": {"38341003", "59621000"}, "dyslipidemia": {"55822004", "370992007"},
              "prior_cvd": {"22298006", "53741008", "230690007"}}
LOINC = {"hba1c": "4548-4", "fasting_glucose": "2345-7", "bmi": "39156-5", "height_cm": "8302-2", "weight_kg": "29463-7",
         "ldl": "18262-6", "hdl": "2085-9", "triglycerides": "2571-8", "total_chol": "2093-3", "egfr": "33914-3",
         "creatinine": "38483-4", "sbp": "8480-6", "dbp": "8462-4"}


def convert(synthea_dir: Path, seed: int = 0) -> pd.DataFrame:
    pts = pd.read_csv(synthea_dir / "patients.csv")
    cond = pd.read_csv(synthea_dir / "conditions.csv", dtype={"CODE": str})
    obs = pd.read_csv(synthea_dir / "observations.csv", dtype={"CODE": str})
    meds = pd.read_csv(synthea_dir / "medications.csv")

    t2d = set(cond.loc[cond["CODE"] == T2D, "PATIENT"])
    pts = pts[pts["Id"].isin(t2d) & pts["DEATHDATE"].isna()].copy()
    rng = np.random.default_rng(seed)
    # priors for fields Synthea does not provide (imputed, flagged)
    prior, _ = generate_ehr(len(pts), rng)
    out = prior.copy()
    out.index = pd.Index([f"TWN-S{i:05d}" for i in range(len(pts))], name="patient_id")  # pseudonymous, no Synthea UUIDs
    ref = pd.Timestamp.now()
    births = pd.to_datetime(pts["BIRTHDATE"]).to_numpy()
    out["age"] = ((ref - pd.to_datetime(births)).days // 365).astype(int).to_numpy()
    out["sex"] = np.where(pts["GENDER"].to_numpy() == "M", "M", "F")

    obs = obs.sort_values("DATE")
    latest = obs.groupby(["PATIENT", "CODE"])["VALUE"].last()
    for col, code in LOINC.items():
        vals = [pd.to_numeric(latest.get((pid, code), np.nan), errors="coerce") for pid in pts["Id"]]
        v = np.array(vals, dtype=float)
        out[col] = np.where(np.isnan(v), out[col].to_numpy(dtype=float), v)
    for col, codes in CONDITIONS.items():
        has = set(cond.loc[cond["CODE"].isin(codes), "PATIENT"])
        out[col] = pts["Id"].isin(has).to_numpy()
    dx = cond[cond["CODE"] == T2D].groupby("PATIENT")["START"].min()
    out["years_since_dx"] = [round((ref - pd.Timestamp(dx[p])).days / 365.25, 1) for p in pts["Id"]]
    out["age_at_dx"] = out["age"] - out["years_since_dx"]
    active = meds[meds["STOP"].isna()]
    desc = active.groupby("PATIENT")["DESCRIPTION"].apply(lambda s: " | ".join(s).lower())
    d = [desc.get(p, "") for p in pts["Id"]]
    out["metformin_mg"] = [1000 if "metformin" in x else 0 for x in d]
    out["sulfonylurea_mg"] = [2 if any(k in x for k in ("glipizide", "glimepiride", "glyburide", "gliclazide")) else 0 for x in d]
    out["dpp4"] = ["gliptin" in x for x in d]
    out["sglt2"] = ["gliflozin" in x for x in d]
    out["insulin_type"] = ["premix_30_70" if "70/30" in x else ("basal_glargine" if "glargine" in x or "insulin" in x else "none") for x in d]
    out["bmi_band_sa"] = bmi_band(out["bmi"].to_numpy())
    out["ckd_stage"] = ckd_stage(out["egfr"].to_numpy())
    out["source"] = "synthea+imputed(india_context,genetics)"
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--synthea-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("data/ehr/patients_synthea.csv"))
    a = ap.parse_args()
    df = convert(a.synthea_dir)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out)
    print(f"wrote {len(df)} T2D patients -> {a.out}")


if __name__ == "__main__":
    main()
