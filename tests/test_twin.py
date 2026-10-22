"""Twin simulator, what-if engine and (if trained models exist) the live prediction path."""
import numpy as np
import pandas as pd
import pytest

from conftest import needs_models
from data_gen.ehr_generator import ehr_feature_matrix
from data_gen.world import World
from ml.features import FRAME_COLUMNS
from twin.simulator import PersonalizedSimulator
from twin.whatif import run_what_if


def _twin_sim(small_cohort):
    p, _, _ = small_cohort
    sim = PersonalizedSimulator(p.iloc[0])
    sim.state.G[:] = 140
    sim.state.Gi[:] = 140
    return sim


def test_what_if_directions(small_cohort):
    sim = _twin_sim(small_cohort)
    now = pd.Timestamp("2026-02-10 18:00")
    res = run_what_if(sim, now, [
        {"name": "meal", "interventions": [{"type": "meal", "carbs": 80, "gi": "high", "in_min": 0}]},
        {"name": "meal+walk", "interventions": [{"type": "meal", "carbs": 80, "gi": "high", "in_min": 0},
                                                {"type": "exercise", "minutes": 30, "intensity": "moderate", "in_min": 15}]},
    ])
    meal, walk = res["scenarios"]
    assert meal["summary"]["peak"] > res["baseline"]["summary"]["peak"] + 30
    assert walk["summary"]["peak"] < meal["summary"]["peak"]
    assert len(res["times"]) == res["horizon_min"] // 5 == len(meal["trajectory"])


def test_what_if_dinner_time_and_sleep(small_cohort):
    sim = _twin_sim(small_cohort)
    now = pd.Timestamp("2026-02-10 18:00")
    res = run_what_if(sim, now, [
        {"name": "19", "interventions": [{"type": "meal", "carbs": 60, "at": "19:00"}]},
        {"name": "21", "interventions": [{"type": "meal", "carbs": 60, "at": "21:00"}]},
    ])
    t19, t21 = (np.argmax(s["trajectory"]) for s in res["scenarios"])
    assert t21 - t19 >= 20  # peak shifts by ~2 h (24 steps)
    # after 19:00 has passed, both dinners move to tomorrow (same day) and both still take effect
    late = run_what_if(sim, pd.Timestamp("2026-02-10 20:10"), [
        {"name": "19", "interventions": [{"type": "meal", "carbs": 60, "at": "19:00"}]},
        {"name": "21", "interventions": [{"type": "meal", "carbs": 60, "at": "21:00"}]},
    ])
    assert all(s["summary"]["delta_peak"] > 20 for s in late["scenarios"])
    assert any("tomorrow" in n or "scheduled" in n for n in late["notes"])
    sl = run_what_if(sim, now, [{"name": "5h", "interventions": [{"type": "sleep", "hours": 5}]},
                                {"name": "8h", "interventions": [{"type": "sleep", "hours": 8}]}])
    assert sl["notes"] and sl["scenarios"][0]["summary"]["peak"] > sl["scenarios"][1]["summary"]["peak"]


def test_calibration_improves_fit(small_cohort, sensor_cfg, start):
    p, lat, params = small_cohort
    w = World(p, lat, params, start, 11, sensor_cfg)
    recs, evs = w.run(1.5)
    from ml.features import build_frame

    pid = p.index[2]
    frame = build_frame(recs[recs.patient_id == pid], evs[(evs.patient_id == pid) & evs.logged])
    sim = PersonalizedSimulator(p.loc[pid])
    res = sim.calibrate(frame)
    assert res["rmse"] <= res["prior_rmse"] + 1e-6


@needs_models
@pytest.mark.parametrize("kind", ["gbm", "deep"])
def test_live_twin_prediction(kind):
    from common import path_of
    from twin.predictor import Predictor
    from twin.twin import DigitalTwin

    d = path_of("data_dir")
    patients = pd.read_csv(d / "ehr" / "patients.csv", index_col="patient_id")
    wear = pd.read_parquet(d / "stream" / "wearables.parquet")
    events = pd.read_parquet(d / "stream" / "events.parquet")
    pid = patients.index[0]
    tw = DigitalTwin(pid, patients.loc[pid].to_dict(), ehr_feature_matrix(patients).loc[pid], Predictor(model=kind))
    rows = wear[wear.patient_id == pid].head(600)
    ev = events[events.patient_id == pid]
    for r in rows.to_dict("records"):
        e = ev[(ev.ts > r["ts"] - pd.Timedelta(minutes=5)) & (ev.ts <= r["ts"])].to_dict("records")
        tw.ingest(r, e)
    p = tw.update_prediction(explain=True)
    assert 0 <= p["risk"] <= 1 and p["level"] in {"GREEN", "AMBER", "RED", "HIGH"}
    assert [f["minutes"] for f in p["forecast"]] == [30, 60, 90, 120]
    assert all(f["p10"] <= f["p50"] <= f["p90"] for f in p["forecast"])
    assert p["explanation"] and {"title", "text", "contribution"} <= set(p["explanation"][0])
    assert list(tw.frame().columns) == FRAME_COLUMNS
    det = tw.detail()
    assert det["series"] and det["agp"] and "glucose_true" not in det["series"][0]
    hist = tw.predictor.predict_many(tw.frame(), tw.ehr_encoded, 24)
    assert len(hist) == 24 and abs((hist[-1]["risk"] or p["risk"]) - p["risk"]) < 1e-3  # batched == single
