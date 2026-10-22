"""Synthetic data generator: realism, EHR -> physiology link, determinism, injections."""
import numpy as np
import pandas as pd

from data_gen.ehr_generator import bmi_band, ehr_feature_matrix, generate_ehr
from data_gen.physiology import MinuteInputs, PhysioState, eag_from_hba1c, step
from data_gen.world import World, calibrate_basal, hypnogram


def test_ehr_plausible_and_pseudonymous():
    p, lat = generate_ehr(300, np.random.default_rng(0))
    assert p.index.str.fullmatch(r"TWN-[0-9A-F]{6}").all()
    assert p.index.is_unique
    assert p["hba1c"].between(5.8, 13.5).all()
    assert 7.0 < p["hba1c"].mean() < 9.5
    assert np.corrcoef(p["hba1c"], p["fasting_glucose"])[0, 1] > 0.7  # correlated labs
    assert (p["metformin_mg"][p["egfr"] < 30] == 0).all()  # metformin contraindicated
    assert set(p["staple"]) <= {"rice", "wheat", "millet"}
    assert list(bmi_band(np.array([22.9, 23.0, 25.0]))) == ["normal", "overweight", "obese"]  # South-Asian cut-offs
    assert not set(lat.columns) & set(p.columns)  # hidden traits never leak into the EHR table
    X = ehr_feature_matrix(p)
    assert X.notna().all().all() and X.columns.str.startswith("ehr_").all()


def _sim(params, inputs: dict[str, float], minutes=240, at=0, n=1):
    st = PhysioState.initial(params)
    peak = []
    z = np.zeros(params.n)
    for t in range(minutes):
        u = {k: z.copy() for k in MinuteInputs.__dataclass_fields__}
        if t == at:
            for k, v in inputs.items():
                u[k] = z + v
        if "activity_dur" in inputs and at <= t < at + inputs["activity_dur"]:
            u["activity"] = z + 0.5
        u.pop("activity_dur", None)
        step(st, params, MinuteInputs(**{k: u[k] for k in MinuteInputs.__dataclass_fields__}), (12 * 60 + t) % 1440)
        peak.append(st.G.copy())
    return np.array(peak)


def test_physiology_directions(small_cohort):
    _, _, params = small_cohort
    base = _sim(params, {})
    meal = _sim(params, {"carb_fast": 50_000, "carb_slow": 20_000})
    assert (meal.max(0) - base.max(0) > 30).all()  # a 70 g meal raises glucose
    walk = _sim(params, {"carb_fast": 50_000, "carb_slow": 20_000, "activity_dur": 30})
    assert (walk.max(0) <= meal.max(0) + 1e-6).all() and (walk.mean(0) < meal.mean(0)).all()  # walking blunts it
    met = _sim(params, {"carb_fast": 50_000, "carb_slow": 20_000, "met": 1.0})
    on_met = params.met_emax > 0
    assert (met.mean(0)[on_met] < meal.mean(0)[on_met]).all()  # metformin lowers glucose


def test_sleep_loss_reduces_insulin_sensitivity(small_cohort):
    _, _, params = small_cohort
    st_good, st_bad = PhysioState.initial(params), PhysioState.initial(params)
    st_bad.sleep_mult[:] = 0.8
    z = np.zeros(params.n)
    for t in range(240):
        u = MinuteInputs(**{k: z.copy() for k in MinuteInputs.__dataclass_fields__})
        if t == 0:
            u.carb_fast = z + 50_000
        step(st_good, params, u, 480 + t)
        step(st_bad, params, u, 480 + t)
    assert (st_bad.G >= st_good.G - 1e-9).all()


def test_world_deterministic_and_calibrated(small_cohort, sensor_cfg, start):
    p, lat, params = small_cohort
    params = calibrate_basal(p, lat, params, start, 1, sensor_cfg, days=2, iters=3)
    w1, _ = World(p, lat, params, start, 7, sensor_cfg).run(2)
    w2, _ = World(p, lat, params, start, 7, sensor_cfg).run(2)
    pd.testing.assert_frame_equal(w1, w2)
    mean = w1.groupby("patient_id")["glucose_true"].mean().loc[p.index]
    err = mean.to_numpy() - eag_from_hba1c(p["hba1c"].to_numpy())
    assert np.abs(err).mean() < 25  # simulated mean glucose tracks HbA1c-implied eAG
    assert w1["cgm"].isna().mean() < 0.1
    assert set(w1["sleep_stage"].unique()) <= {0, 1, 2, 3}


def test_injections_change_the_world(small_cohort, sensor_cfg, start):
    p, lat, params = small_cohort
    a = World(p, lat, params, start, 3, sensor_cfg)
    b = World(p, lat, params, start, 3, sensor_cfg)
    for w in (a, b):
        w.run(0.5)
    b.inject_meal(0, 120, 0.8)
    b.inject_dropout(1, 60)
    ra, _ = a.run(0.125)
    rb, eb = b.run(0.125)
    ga = ra[ra.patient_id == p.index[0]]["glucose_true"].max()
    gb = rb[rb.patient_id == p.index[0]]["glucose_true"].max()
    assert gb > ga + 40
    assert rb[rb.patient_id == p.index[1]]["cgm"].isna().sum() >= 10
    assert ((eb["type"] == "meal") & eb["injected"]).any()


def test_hypnogram_structure():
    h = hypnogram(420, False, np.random.default_rng(0))
    assert len(h) == 420
    first_half_deep = (h[:210] == 2).mean()
    second_half_deep = (h[210:] == 2).mean()
    assert first_half_deep > second_half_deep  # deep sleep front-loaded
    assert (h[210:] == 3).mean() > (h[:210] == 3).mean()  # REM back-loaded
