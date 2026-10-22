"""Standalone stream simulator that pushes wearable records to a backend over HTTP.

This is the "device gateway" deployment. Start the backend with ``DT_STREAM_MODE=external``, then::

    python -m backend.stream_client --url http://127.0.0.1:8000 --speed 60

The backend in external mode still warms up its twins from its own simulated history. This client
fast-forwards the *same* deterministic world (same seed, start day and clock) through that warm-up,
then posts one record per patient every 5 simulated minutes.
"""
from __future__ import annotations

import argparse
import json
import time

import httpx
import pandas as pd

from common import get_config, get_logger, path_of
from data_gen.physiology import PhysioParams
from data_gen.world import World
from twin.twin import DEVICE_FIELDS

log = get_logger("stream_client")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--speed", type=float, default=60, help="simulated seconds per wall-clock second")
    ap.add_argument("--blocks", type=int, default=10**9, help="number of 5-min blocks to send")
    ap.add_argument("--start-clock", default="17:30", help="must match the backend's DT_START_CLOCK")
    a = ap.parse_args()
    cfg = get_config()
    d = path_of("data_dir")
    patients = pd.read_csv(d / "ehr" / "patients.csv", index_col="patient_id")
    latent = pd.read_csv(d / "ehr" / "latent_truth.csv", index_col="patient_id")
    split = json.loads((path_of("artifacts_dir") / "splits.json").read_text())
    ids = sorted(split["test"])[: cfg["serving"]["demo_patients"]]
    world = World(patients.loc[ids], latent.loc[ids], PhysioParams.from_frame(latent.loc[ids]),
                  pd.Timestamp(cfg["cohort"]["start_date"]), cfg["seed"] + 99, cfg["simulation"]["sensor"],
                  start_day=cfg["cohort"]["n_days"])
    # fast-forward through the backend's warm-up (deterministic world -> identical state)
    hh, mm = (int(x) for x in a.start_clock.split(":"))
    for _ in range((14 * 1440 + hh * 60 + mm) // 5):
        world.advance_block()
    with httpx.Client(base_url=a.url, timeout=30) as client:
        for _ in range(a.blocks):
            rec, evs = world.advance_block()
            ts = world.now().isoformat()
            for i, pid in enumerate(ids):
                record = {"ts": ts, **{k: (None if pd.isna(rec[k][i]) else float(rec[k][i])) for k in DEVICE_FIELDS}}
                events = [{"ts": (world.start + pd.Timedelta(minutes=e.minute)).isoformat(), "type": e.type, "name": e.name,
                           "label": e.label, "logged_amount": e.logged_amount} for e in evs if e.patient == i and e.logged]
                client.post("/api/ingest", json={"patient_id": pid, "record": record, "events": events}).raise_for_status()
            log.info("sent block %s", ts)
            time.sleep(300 / a.speed)


if __name__ == "__main__":
    main()
