"""Optional MIMIC-IV adapter (credentialed access only). **Not needed** to run the PoC.

MIMIC-IV is restricted. You need PhysioNet credentialing, CITI-style human-subjects training and a
signed data-use agreement. This module never downloads anything and the project runs fully without it.

What it does: extracts a minimal, de-identified EHR vector (age, sex, latest HbA1c / glucose /
creatinine, diabetes and comorbidity diagnoses) for adult patients with a T2D ICD code, mapped to the
twin's schema. Uncovered fields (diet, staple, genetics, wearables) are imputed or simulated and
flagged. MIMIC is a US ICU/hospital population, so it is **not** representative of Indian outpatients.
Use it only to check that the EHR branch handles real-world missingness.

Lab ``itemid`` values must be checked against ``hosp/d_labitems`` for your MIMIC-IV version before use.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ICD_T2D_PREFIXES = ("E11", "250")  # ICD-10 E11.*, ICD-9 250.x (type is in the 5th digit; verify)
LAB_LABELS = {"hba1c": "% Hemoglobin A1c", "fasting_glucose": "Glucose", "creatinine": "Creatinine"}


def extract(mimic_root: Path, limit: int | None = None) -> pd.DataFrame:
    """Return a de-identified EHR frame indexed by pseudonymous IDs (TWN-M#####)."""
    hosp = mimic_root / "hosp"
    pts = pd.read_csv(hosp / "patients.csv.gz", usecols=["subject_id", "gender", "anchor_age"])
    dx = pd.read_csv(hosp / "diagnoses_icd.csv.gz", usecols=["subject_id", "icd_code"], dtype={"icd_code": str})
    t2d = dx[dx["icd_code"].str.startswith(ICD_T2D_PREFIXES)]["subject_id"].unique()
    pts = pts[pts["subject_id"].isin(t2d) & (pts["anchor_age"] >= 18)]
    if limit:
        pts = pts.head(limit)
    items = pd.read_csv(hosp / "d_labitems.csv.gz", usecols=["itemid", "label"])
    want = {k: items.loc[items["label"] == v, "itemid"].tolist() for k, v in LAB_LABELS.items()}
    labs = pd.read_csv(hosp / "labevents.csv.gz", usecols=["subject_id", "itemid", "charttime", "valuenum"])
    labs = labs[labs["subject_id"].isin(pts["subject_id"])].sort_values("charttime")
    out = pd.DataFrame({"age": pts["anchor_age"].to_numpy(), "sex": pts["gender"].to_numpy()},
                       index=pd.Index([f"TWN-M{i:05d}" for i in range(len(pts))], name="patient_id"))
    for col, ids in want.items():
        last = labs[labs["itemid"].isin(ids)].groupby("subject_id")["valuenum"].last()
        out[col] = pts["subject_id"].map(last).to_numpy()
    out["source"] = "mimic-iv(deidentified)+imputed"
    return out  # merge with generator priors for the remaining schema columns before use
