"""Generate the synthetic cohort: EHR (Stream A) + wearable/CGM stream (Stream B).

Usage::

    python -m data_gen.generate                      # config defaults (150 patients x 30 days)
    python -m data_gen.generate --patients 40 --days 7
"""
from __future__ import annotations

import argparse
import json
import time

import numpy as np
import pandas as pd

from common import get_config, get_logger, path_of, seed_everything
from common.glycemic import spike_onsets
from data_gen.ehr_generator import generate_ehr
from data_gen.fhir import to_fhir_bundle
from data_gen.physiology import gmi_from_mean, params_from_ehr
from data_gen.world import World, calibrate_basal

log = get_logger("data_gen")
GENERATOR_VERSION = "1.0.0"


def summarize(patients: pd.DataFrame, wear: pd.DataFrame, events: pd.DataFrame) -> dict:
    """Cohort-level realism checks (printed and stored in the manifest)."""
    g = wear["cgm"]
    per = wear.groupby("patient_id")
    mean_cgm = per["cgm"].mean()
    gmi = gmi_from_mean(mean_cgm)
    hba1c = patients.loc[mean_cgm.index, "hba1c"]
    above = (wear["cgm"] > 180).astype(float).where(g.notna())
    onset = np.concatenate([spike_onsets(x.to_numpy()) for _, x in per["cgm"]])
    days = (wear["ts"].max() - wear["ts"].min()).total_seconds() / 86400
    meals = events[events["type"] == "meal"]
    return {
        "patients": int(len(patients)),
        "days": round(days, 1),
        "rows": int(len(wear)),
        "cgm_mean": round(float(g.mean()), 1),
        "cgm_sd": round(float(g.std()), 1),
        "tir_70_180_pct": round(float(((g >= 70) & (g <= 180)).sum() / g.notna().sum() * 100), 1),
        "tar_180_pct": round(float(above.mean() * 100), 1),
        "tbr_70_pct": round(float((g < 70).sum() / g.notna().sum() * 100), 2),
        "cgm_missing_pct": round(float(g.isna().mean() * 100), 1),
        "hr_missing_pct": round(float(wear["hr"].isna().mean() * 100), 1),
        "spike_onsets_per_patient_day": round(float(onset.sum() / len(patients) / days), 2),
        "gmi_vs_hba1c_corr": round(float(np.corrcoef(gmi, hba1c)[0, 1]), 3),
        "gmi_minus_hba1c_mean": round(float((gmi - hba1c).mean()), 2),
        "meals_per_patient_day": round(len(meals) / len(patients) / days, 2),
        "meal_log_rate": round(float(meals["logged"].mean()), 2) if len(meals) else 0.0,
        "mean_hba1c": round(float(patients["hba1c"].mean()), 2),
    }


def generate(n_patients: int, n_days: int, seed: int) -> dict:
    cfg = get_config()
    seed_everything(seed)
    rng = np.random.default_rng(seed)
    start = pd.Timestamp(cfg["cohort"]["start_date"])
    sensor = cfg["simulation"]["sensor"]
    t0 = time.time()

    patients, latent = generate_ehr(n_patients, rng, cfg["cohort"]["urban_fraction"])
    log.info("EHR: %d patients (mean HbA1c %.2f)", len(patients), patients["hba1c"].mean())

    params = params_from_ehr(patients, latent, rng)
    params = calibrate_basal(patients, latent, params, start, seed + 1, sensor, days=cfg["simulation"]["calibration_days"])
    log.info("Calibrated basal set-points (%.1fs)", time.time() - t0)

    world = World(patients, latent, params, start, seed + 2, sensor)
    wear, events = world.run(n_days)
    log.info("Stream: %d rows, %d events (%.1fs)", len(wear), len(events), time.time() - t0)

    data_dir = path_of("data_dir")
    (data_dir / "ehr").mkdir(parents=True, exist_ok=True)
    (data_dir / "stream").mkdir(parents=True, exist_ok=True)
    patients.to_csv(data_dir / "ehr" / "patients.csv")
    latent.join(params.to_frame(latent.index), rsuffix="_param").to_csv(data_dir / "ehr" / "latent_truth.csv")
    with open(data_dir / "ehr" / "fhir_bundle.json", "w", encoding="utf-8") as f:
        json.dump(to_fhir_bundle(patients), f, indent=1)
    wear.to_parquet(data_dir / "stream" / "wearables.parquet", index=False)
    events.to_parquet(data_dir / "stream" / "events_truth.parquet", index=False)
    events[events["logged"]].drop(columns=["amount"]).to_parquet(data_dir / "stream" / "events.parquet", index=False)

    summary = summarize(patients, wear, events)
    manifest = {
        "generator": "custom-indian-t2d", "generator_version": GENERATOR_VERSION, "seed": seed,
        "start_date": str(start.date()), "synthetic_only": True, "summary": summary,
        "sources": ["Custom synthetic Indian T2D EHR generator", "Physiological world simulator (extended Bergman minimal model)"],
    }
    with open(data_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    log.info("Summary: %s", json.dumps(summary))
    log.info("Done in %.1fs -> %s", time.time() - t0, data_dir)
    return summary


def main() -> None:
    cfg = get_config()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--patients", type=int, default=cfg["cohort"]["n_patients"])
    ap.add_argument("--days", type=int, default=cfg["cohort"]["n_days"])
    ap.add_argument("--seed", type=int, default=cfg["seed"])
    a = ap.parse_args()
    generate(a.patients, a.days, a.seed)


if __name__ == "__main__":
    main()
