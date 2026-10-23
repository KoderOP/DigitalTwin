"""Simulated behaviour-response study (SIMULATION, NOT CLINICAL EVIDENCE).

Question: if virtual patients follow the app's suggestions, does their predicted/observed spike
frequency go down? This only shows that the closed loop (model -> suggestion -> behaviour ->
physiology) works *inside our simulator*. It says nothing about real patients.

Design (paired): the same held-out test patients, the same seed, the same days. In each arm the
virtual patient's world consumes random numbers identically; interventions are applied without
touching the RNG, so meals, sleep and sensor noise are the same in every arm.
  * control         - no app
  * follow_50       - follows each suggestion with probability 0.5 (decided by a separate RNG)
  * follow_100      - always follows
Every 30 simulated minutes the twin predicts. If the patient-app logic would show a "walk now" or
"swap rice" suggestion (AMBER/RED/HIGH, see backend.portal.explain_text.next_action), the patient
does a 15-min brisk walk, or eats roti/millet instead of rice at the next meal (-30% carbs, slower
absorption).

    python -m ml.behaviour_sim --days 3
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time

import numpy as np
import pandas as pd

from common import get_config, get_logger, path_of
from common.glycemic import spike_onsets, summary_metrics

log = get_logger("ml.behaviour_sim")
DAY_BLOCKS = 288


def _walk(world, i: int, minutes: int = 15) -> None:
    world._put("activity", i, world.minute, 0.55, minutes, add=False)
    world._put("steps", i, world.minute, np.full(minutes, 105.0, dtype=np.float32), minutes, add=False)


def _swap_next_meal(world, i: int, horizon_min: int = 180) -> bool:
    """Roti/millet instead of rice: next planned meal within the horizon gets 30% fewer carbs, more slowly absorbed."""
    for e in world.events:
        if e.patient == i and e.type == "meal" and world.minute <= e.minute < world.minute + horizon_min:
            a = e.minute - world.buf_start
            fast = world.buf["carb_fast"][i, a:a + 15].copy()
            slow = world.buf["carb_slow"][i, a:a + 15].copy()
            total = (fast + slow) * 0.7
            world.buf["carb_fast"][i, a:a + 15] = total * 0.4
            world.buf["carb_slow"][i, a:a + 15] = total * 0.6
            return True
    return False


def run_arm(adherence: float, days: int, n: int, seed: int) -> dict:
    from backend.engine import Engine
    from backend.portal.config_schema import PortalConfig
    from backend.portal.explain_text import next_action

    eng = Engine(n_patients=n, warmup_days=3, start_clock="06:00")
    cfg = PortalConfig().model_dump()
    rng = np.random.default_rng(seed)  # adherence decisions only (separate from the world RNG)
    w = eng.world
    cgm: dict[str, list[float]] = {pid: [] for pid in eng.ids}
    followed = suggested = 0
    t0 = time.time()
    for b in range(days * DAY_BLOCKS):
        rec, evs = w.advance_block()
        eng._ingest_block(rec, evs, calibrate=False, predict=False)
        for k, pid in enumerate(eng.ids):
            cgm[pid].append(float(rec["cgm"][k]))
        if adherence > 0 and b % 6 == 0:
            now = w.now()
            for k, pid in enumerate(eng.ids):
                tw = eng.twins[pid]
                p = tw.update_prediction(explain=False)
                act = next_action(p, tw.rows[-1]["cgm"], p["features"], cfg, "en", now)
                if act["key"] in ("walk_now", "swap_rice"):
                    suggested += 1
                    if rng.random() < adherence:
                        followed += 1
                        if act["key"] == "walk_now":
                            _walk(w, k)
                        else:
                            _swap_next_meal(w, k)
    out = {"adherence": adherence, "suggestions": suggested, "followed": followed, "seconds": round(time.time() - t0, 1), "patients": {}}
    for pid, g in cgm.items():
        arr = np.array(g)
        m = summary_metrics(arr)
        out["patients"][pid] = {"onsets_per_day": float(spike_onsets(arr).sum() / days), "tar": m["tar"], "tir": m["tir"],
                                "mean": m["mean"], "tbr": m["tbr"]}
    return out


def summarise(arms: dict[str, dict]) -> dict:
    s = {}
    for name, a in arms.items():
        df = pd.DataFrame(a["patients"]).T
        s[name] = {"onsets_per_patient_day": round(float(df.onsets_per_day.mean()), 2), "tar_pct": round(float(df.tar.mean()), 1),
                   "tir_pct": round(float(df.tir.mean()), 1), "tbr_pct": round(float(df.tbr.mean()), 2), "mean_glucose": round(float(df["mean"].mean()), 1),
                   "suggestions": a["suggestions"], "followed": a["followed"]}
    base = pd.DataFrame(arms["control"]["patients"]).T
    for name in arms:
        if name == "control":
            continue
        df = pd.DataFrame(arms[name]["patients"]).T.loc[base.index]
        d = df.onsets_per_day - base.onsets_per_day
        s[name]["paired_delta_onsets_per_day"] = round(float(d.mean()), 2)
        s[name]["patients_improved"] = int((d < 0).sum())
        s[name]["patients_worse"] = int((d > 0).sum())
    return s


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--patients", type=int, default=12)
    a = ap.parse_args()
    os.environ["DT__PATHS__DB_PATH"] = os.path.join(tempfile.mkdtemp(), "sim.sqlite3")  # keep the demo audit trail clean
    get_config.cache_clear()
    arms = {}
    for name, adh in (("control", 0.0), ("follow_50", 0.5), ("follow_100", 1.0)):
        log.info("arm %s ...", name)
        arms[name] = run_arm(adh, a.days, a.patients, seed=11)
    summ = summarise(arms)
    rep = path_of("reports_dir")
    (rep / "behaviour_response.json").write_text(json.dumps({"summary": summ, "arms": arms, "days": a.days, "patients": a.patients},
                                                            indent=1), encoding="utf-8")
    render(summ, a.days, a.patients)
    log.info("summary %s", json.dumps(summ))


def render(summ: dict, days: int, patients: int) -> None:
    """Write reports/behaviour_response.md from computed numbers (also usable on the saved JSON)."""
    rep = path_of("reports_dir")
    a = argparse.Namespace(days=days, patients=patients)
    lines = [
        "# Simulated behaviour-response study",
        "",
        "> **SIMULATION ONLY. NOT CLINICAL EVIDENCE.** Virtual patients from the held-out test split follow the patient app's "
        "lifestyle suggestions inside the same simulator that generated the training data. This checks that the closed loop "
        "works mechanically. It does not show that real people would benefit.",
        "",
        f"Setup: {a.patients} patients x {a.days} simulated days, paired arms (identical meals, sleep and sensor noise). Suggestions are "
        "evaluated every 30 min with the served model and the app's next-action rules. Following means a 15-min brisk walk, or "
        "roti/millet instead of rice at the next meal (-30% carbs, slower absorption).",
        "",
        "| Arm | Spike onsets / patient-day | Paired change vs control | Patients improved / worse | Time > 180 (%) | TIR (%) | TBR (%) | Mean glucose | Suggestions followed |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, r in summ.items():
        lines.append(f"| {name} | {r['onsets_per_patient_day']} | {r.get('paired_delta_onsets_per_day', '–')} | "
                     f"{r.get('patients_improved', '–')} / {r.get('patients_worse', '–')} | {r['tar_pct']} | {r['tir_pct']} | {r['tbr_pct']} | "
                     f"{r['mean_glucose']} | {r['followed']}/{r['suggestions']} |")
    lines += [
        "",
        "**How to read this.** *Time > 180* is the more stable outcome. *Spike onsets* counts sustained crossings above "
        "180 mg/dL, and a walk in the middle of an excursion can split one long episode into two short ones. So onset counts "
        "need not fall monotonically with adherence, even when total time above range does. TBR (time below 70) is "
        "reported to check that the suggestions do not create hypoglycaemia in the simulator. Very few patients and days: "
        "treat this as a mechanism check only.",
        "",
        "Generated by `python -m ml.behaviour_sim`. Numbers are computed, not edited.",
    ]
    (rep / "behaviour_response.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
