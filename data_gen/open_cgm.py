"""Optional loader for open CGM datasets -> the twin's 5-minute wearable schema.

The PoC never downloads data. To use a public dataset, download it yourself from its official host,
accept its licence or data-use terms, and point this loader at the files. Candidate datasets (search by
name, and verify licence and column names for the release you download):

* **Shanghai T1DM and T2DM datasets** (Zhao et al., *Scientific Data*, 2023): CGM every 15 min with
  dietary and medication records from Chinese patients. The closest public analogue to an Asian T2D
  population.
* **CGMacros** (PhysioNet): CGM with detailed macronutrient meal logs and wearable data. Needs a
  PhysioNet account and a signed data-use agreement.
* **D1NAMO** (Dubosson et al., 2018): T1D cohort with CGM, ECG, breathing and accelerometry plus food
  pictures. Useful to test the wearable channels, but not T2D.

Usage::

    python -m data_gen.open_cgm --csv path/to/file.csv --time-col Date --glucose-col "Dexcom GL" \
        --patient-id OPEN-001 --unit mg/dL --out data/stream/open_cgm.parquet

The output has the same columns as ``data/stream/wearables.parquet`` (non-CGM channels are NaN unless
mapped), so it can be replayed into a twin for qualitative testing. Never feed identifiable data into
the PoC.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

WEAR_COLUMNS = ["patient_id", "ts", "cgm", "hr", "hrv_rmssd", "steps", "activity", "sleep_stage", "spo2", "skin_temp"]


def load_cgm_csv(path: Path, time_col: str, glucose_col: str, patient_id: str, unit: str = "mg/dL",
                 extra: dict[str, str] | None = None) -> pd.DataFrame:
    """Read a CGM CSV, convert units, resample to 5 min (gaps stay NaN) and map optional extra columns."""
    raw = pd.read_csv(path)
    df = pd.DataFrame({"ts": pd.to_datetime(raw[time_col], errors="coerce"),
                       "cgm": pd.to_numeric(raw[glucose_col], errors="coerce")}).dropna(subset=["ts"])
    if unit.lower() in ("mmol/l", "mmol"):
        df["cgm"] = df["cgm"] * 18.0
    for target, source in (extra or {}).items():
        df[target] = pd.to_numeric(raw.loc[df.index, source], errors="coerce")
    df = df.set_index("ts").sort_index().resample("5min").mean()  # 15-min sources leave NaN gaps (handled by imputation)
    df = df.reset_index()
    df.insert(0, "patient_id", patient_id)
    for c in WEAR_COLUMNS:
        if c not in df:
            df[c] = np.nan
    df["sleep_stage"] = df["sleep_stage"].fillna(0).astype("int8")
    return df[WEAR_COLUMNS]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--time-col", required=True)
    ap.add_argument("--glucose-col", required=True)
    ap.add_argument("--patient-id", default="OPEN-001")
    ap.add_argument("--unit", default="mg/dL")
    ap.add_argument("--out", type=Path, default=Path("data/stream/open_cgm.parquet"))
    a = ap.parse_args()
    df = load_cgm_csv(a.csv, a.time_col, a.glucose_col, a.patient_id, a.unit)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(a.out, index=False)
    print(f"{len(df)} rows ({df['cgm'].notna().mean():.0%} with CGM) -> {a.out}")


if __name__ == "__main__":
    main()
