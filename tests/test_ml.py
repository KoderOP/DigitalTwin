"""Feature causality, labels, alert maths, metrics and model shapes."""
import numpy as np
import pandas as pd
import torch

from common.glycemic import spike_onsets, summary_metrics
from ml.alerting import choose_thresholds, simulate_alerts
from ml.deep import FusionNet, pinball
from ml.features import labels, seq_channels, wearable_features


def _frame(n=600, seed=0):
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2026-01-01", periods=n, freq="5min")
    g = 140 + 50 * np.sin(np.arange(n) / 30) + rng.normal(0, 5, n)
    df = pd.DataFrame({"ts": ts, "cgm": g, "hr": 70 + rng.normal(0, 2, n), "hrv_rmssd": 30 + rng.normal(0, 2, n),
                       "steps": rng.poisson(20, n).astype(float), "activity": 0.05, "sleep_stage": 0, "spo2": 97.0, "skin_temp": 33.0,
                       "carbs": 0.0, "med_met": 0.0, "med_su": 0.0, "med_dpp4": 0.0, "med_sglt2": 0.0, "ins_units": 0.0})
    df.loc[100, "carbs"] = 60
    return df


def test_features_are_causal():
    df = _frame()
    f1 = wearable_features(df)
    df2 = df.copy()
    df2.loc[400:, ["cgm", "hr", "steps"]] = 999  # tamper with the future
    df2.loc[450, "carbs"] = 500
    f2 = wearable_features(df2)
    pd.testing.assert_frame_equal(f1.iloc[:400], f2.iloc[:400])


def test_imputation_handles_dropouts():
    df = _frame()
    df.loc[300:330, "cgm"] = np.nan
    f = wearable_features(df)
    assert f["w_g_now"].notna().all()
    assert f.loc[320, "w_g_age_min"] == (320 - 299) * 5
    assert seq_channels(df).shape == (600, 17) and np.isfinite(seq_channels(df)).all()


def test_labels():
    df = _frame(100)
    df["cgm"] = 120.0
    df.loc[50:52, "cgm"] = 200.0
    lab = labels(df)
    assert lab.loc[30, "y_spike"] == 1  # spike 100 min ahead
    assert lab.loc[20, "y_spike"] == 0  # 150 min ahead: outside the horizon
    assert lab.loc[30, "y_g60"] == 120.0 and lab.loc[38, "y_g60"] == 200.0  # +12 steps = +60 min
    assert not lab.loc[50, "eligible"] and lab.loc[40, "eligible"]


def test_spike_onsets_ignore_flicker():
    g = np.full(60, 170.0)
    g[10] = 185  # single noisy reading: not an onset
    g[30:40] = 200  # sustained: onset at 30
    on = spike_onsets(g)
    assert list(np.flatnonzero(on)) == [30]
    m = summary_metrics(g)
    assert 0 < m["tar"] < 30 and m["tir"] > 70


def test_alert_simulation_lead_time():
    n = 100
    cgm = np.full(n, 150.0)
    cgm[60:70] = 220
    p = np.full(n, 0.1)
    p[40:60] = 0.9  # fires at 40 -> onset at 60: lead 100 min
    p[85] = 0.9  # false alert (no onset afterwards)
    r = simulate_alerts(p, cgm <= 180, cgm, thr=0.5, refractory_steps=12)
    assert r["onsets"] == 1 and r["detected"] == 1 and r["lead_times"] == [100]
    # alerts at 40 and 52 (risk still high after the 60-min refractory) are true; 85 is false
    assert r["alerts"] == 3 and r["true_alerts"] == 2 and r["false_alerts"] == 1


def test_thresholds_ordering():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 2000)
    p = np.clip(y * 0.4 + rng.random(2000) * 0.6, 0, 1)
    t = choose_thresholds(y, p, 0.8, 0.7)
    assert 0 < t["amber"] <= t["red"] <= 1


def test_fusion_net_variants_and_monotone_quantiles():
    seq, tab, st = torch.randn(4, 72, 17), torch.randn(4, 10), torch.randn(4, 8)
    for mode in ("fused", "wearable_only", "ehr_only"):
        for enc in ("gru", "tcn"):
            m = FusionNet(mode, 17, 10, 8, hidden=16, static_hidden=16, encoder=enc, pool=2)
            o = m(seq if mode != "ehr_only" else None, tab, st if mode != "wearable_only" else None)
            assert o["spike"].shape == (4,) and o["q"].shape == (4, 4, 3)
            assert (o["q"][..., 1:] >= o["q"][..., :-1]).all()
    loss = pinball(torch.zeros(2, 4, 3), torch.tensor([[1.0, float("nan"), 0, 0], [0, 0, 0, 0]]), torch.tensor([0.1, 0.5, 0.9]))
    assert torch.isfinite(loss)
