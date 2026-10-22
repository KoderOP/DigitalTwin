"""Minimal FHIR R4 export of the synthetic EHR (Patient, Condition, Observation, MedicationStatement).

This shows the path to ABDM / FHIR interoperability. Codes are illustrative LOINC / SNOMED CT
codes for the concepts used; the export is not a validated FHIR profile.
"""
from __future__ import annotations

import pandas as pd

LOINC = {
    "hba1c": ("4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood", "%"),
    "fasting_glucose": ("1558-6", "Fasting glucose [Mass/volume] in Serum or Plasma", "mg/dL"),
    "ldl": ("13457-7", "LDL Cholesterol (calculated)", "mg/dL"),
    "hdl": ("2085-9", "HDL Cholesterol", "mg/dL"),
    "triglycerides": ("2571-8", "Triglyceride", "mg/dL"),
    "egfr": ("62238-1", "eGFR CKD-EPI", "mL/min/1.73m2"),
    "creatinine": ("2160-0", "Creatinine", "mg/dL"),
    "bmi": ("39156-5", "Body mass index", "kg/m2"),
    "waist_cm": ("8280-0", "Waist circumference", "cm"),
}
SNOMED = {
    "t2d": ("44054006", "Diabetes mellitus type 2"),
    "hypertension": ("38341003", "Hypertensive disorder"),
    "dyslipidemia": ("370992007", "Dyslipidemia"),
    "prior_cvd": ("49601007", "Disorder of cardiovascular system"),
}


def to_fhir_bundle(patients: pd.DataFrame) -> dict:
    """Return a FHIR collection Bundle for all patients (pseudonymous IDs only)."""
    entries: list[dict] = []
    for pid, r in patients.iterrows():
        ref = {"reference": f"Patient/{pid}"}
        entries.append({"resource": {
            "resourceType": "Patient", "id": pid,
            "gender": "male" if r.sex == "M" else "female",
            "extension": [{"url": "urn:dt:age-years", "valueInteger": int(r.age)},
                          {"url": "urn:dt:region", "valueString": r.region}],
            "meta": {"tag": [{"code": "SYNTHETIC", "display": "Synthetic data - not a real person"}]},
        }})
        conds = ["t2d"] + [c for c in ("hypertension", "dyslipidemia", "prior_cvd") if r[c]]
        for c in conds:
            code, disp = SNOMED[c]
            entries.append({"resource": {"resourceType": "Condition", "subject": ref,
                                         "code": {"coding": [{"system": "http://snomed.info/sct", "code": code, "display": disp}]}}})
        for k, (code, disp, unit) in LOINC.items():
            entries.append({"resource": {"resourceType": "Observation", "status": "final", "subject": ref,
                                         "code": {"coding": [{"system": "http://loinc.org", "code": code, "display": disp}]},
                                         "valueQuantity": {"value": float(r[k]), "unit": unit}}})
        meds = []
        if r.metformin_mg:
            meds.append(f"Metformin {r.metformin_mg} mg/day")
        if r.sulfonylurea_mg:
            meds.append(f"Glimepiride {r.sulfonylurea_mg} mg/day")
        if r.dpp4:
            meds.append("Teneligliptin 20 mg/day")
        if r.sglt2:
            meds.append("Dapagliflozin 10 mg/day")
        if r.insulin_type != "none":
            meds.append(f"{r.insulin_type} {r.insulin_units_day} U/day")
        for m in meds:
            entries.append({"resource": {"resourceType": "MedicationStatement", "status": "active", "subject": ref,
                                         "medicationCodeableConcept": {"text": m}}})
    return {"resourceType": "Bundle", "type": "collection", "entry": entries}
