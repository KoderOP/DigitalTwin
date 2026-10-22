"""Train all models (GBM + deep fusion, each in 3 ablation variants), then evaluate.

Usage::

    python -m ml.train            # full training + evaluation report
    python -m ml.train --fast     # quick smoke run (few epochs / trees) for tests
    python -m ml.train --no-eval
"""
from __future__ import annotations

import argparse
import json
import time

import numpy as np

from common import get_config, get_logger, path_of, seed_everything
from ml.dataset import build_cohort, feature_groups, load_raw, matrix, sample_index, save_splits, windows
from ml.deep import train_deep
from ml.gbm import HORIZONS, train_gbm
from ml.predict import deep_arrays, deep_columns

log = get_logger("ml.train")
VARIANTS = ("wearable_only", "ehr_only", "fused")


def _reg_targets(c, idx):
    t = c.table.iloc[idx]
    import pandas as pd

    return pd.DataFrame({f"d{h}": (t[f"y_g{h}"] - t["g_now"]).to_numpy() for h in HORIZONS})


def _deep_split(c, idx, mode, window):
    tab_cols, static_cols = deep_columns(c, mode)
    tab, static = deep_arrays(c, idx, tab_cols, static_cols)
    t = c.table.iloc[idx]
    dg = np.stack([(t[f"y_g{h}"] - t["g_now"]).to_numpy() for h in HORIZONS], axis=1).astype(np.float32)
    return {
        "seq": lambda b, idx=idx: windows(c, idx[b], window),
        "tab": tab, "static": static, "y": t["y_spike"].to_numpy(np.float32),
        "yh": t["y_hypo"].fillna(0).to_numpy(np.float32), "dg": dg,
    }, tab_cols, static_cols


def run(fast: bool = False, evaluate: bool = True) -> dict:
    cfg = get_config()
    seed = seed_everything()
    t0 = time.time()
    art = path_of("artifacts_dir")
    dcfg, gcfg, ncfg = cfg["dataset"], dict(cfg["gbm"]), dict(cfg["deep"])
    if fast:
        gcfg.update(n_estimators=60)
        ncfg.update(epochs=1, ablation_epochs=1)

    patients, wear, events = load_raw()
    c = build_cohort(patients, wear, events)
    save_splits(c.splits, c.cutoff)
    groups = feature_groups(c.feature_cols)
    with open(art / "feature_columns.json", "w", encoding="utf-8") as f:
        json.dump(groups, f, indent=1)

    summary: dict = {"seed": seed, "fast": fast, "gbm": {}, "deep": {}}
    # ---------------- GBM baseline ----------------
    tr = sample_index(c, "train", dcfg["train_stride_min"], "pre")
    va = sample_index(c, "val", dcfg["train_stride_min"], "all")
    Xtr, Xva = matrix(c, tr, groups["fused"]), matrix(c, va, groups["fused"])
    ytr, yva = c.table["y_spike"].to_numpy()[tr], c.table["y_spike"].to_numpy()[va]
    log.info("GBM rows: train %d (pos %.3f), val %d", len(tr), ytr.mean(), len(va))
    for v in VARIANTS:
        t1 = time.time()
        reg = (_reg_targets(c, tr), _reg_targets(c, va)) if v == "fused" else None
        m = train_gbm(v, groups[v], Xtr, ytr, Xva, yva, gcfg, seed, reg)
        m.save(art / f"gbm_{v}.pkl")
        summary["gbm"][v] = {"best_iteration": int(m.clf.best_iteration_ or gcfg["n_estimators"]), "sec": round(time.time() - t1, 1)}

    # ---------------- deep fusion ----------------
    W = dcfg["window_hours"] * 12
    trd = sample_index(c, "train", dcfg["deep_train_stride_min"], "pre")
    vad = sample_index(c, "val", dcfg["deep_train_stride_min"], "all")
    log.info("Deep rows: train %d, val %d, window %d", len(trd), len(vad), W)
    seq_mean = c.seq[trd].mean(axis=0)
    for v in VARIANTS:
        t1 = time.time()
        dtr, tab_cols, static_cols = _deep_split(c, trd, v, W)
        dva, _, _ = _deep_split(c, vad, v, W)
        data = {"train": dtr, "val": dva, "n_seq": c.seq.shape[1], "tab_cols": tab_cols, "static_cols": static_cols,
                "seq_mean": seq_mean, "window": W}
        epochs = ncfg["epochs"] if v == "fused" else ncfg["ablation_epochs"]
        bundle, info = train_deep(v, data, ncfg, seed, epochs)
        bundle.save(art / f"deep_{v}.pt")
        summary["deep"][v] = {**info, "sec": round(time.time() - t1, 1)}

    summary["train_seconds"] = round(time.time() - t0, 1)
    with open(art / "training_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    log.info("Training done in %.0fs", time.time() - t0)

    if evaluate:
        from ml.evaluate import evaluate as run_eval

        run_eval(c, fast=fast)
    log.info("Total %.0fs", time.time() - t0)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--no-eval", action="store_true")
    a = ap.parse_args()
    run(fast=a.fast, evaluate=not a.no_eval)


if __name__ == "__main__":
    main()
