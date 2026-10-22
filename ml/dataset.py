"""Dataset assembly: patient-level splits, feature/label tables and sequence windows.

Split protocol (prevents leakage):
* patients are split 70/15/15 into train / val / test (no patient appears in two splits);
* within *train* patients, the last ``temporal_holdout_frac`` of days is held out as a temporal
  test set, and training rows are restricted so their 120-min label window ends before the cut-off.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from common import get_config, get_logger, path_of
from data_gen.ehr_generator import ehr_feature_matrix
from ml.features import H, build_frame, labels, seq_channels, wearable_features

log = get_logger("ml.dataset")


def load_raw(data_dir: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load (patients, wearables, logged events). Hidden truth columns are dropped here."""
    d = data_dir or path_of("data_dir")
    patients = pd.read_csv(d / "ehr" / "patients.csv", index_col="patient_id")
    wear = pd.read_parquet(d / "stream" / "wearables.parquet").drop(columns=["glucose_true", "stress_true"])
    events = pd.read_parquet(d / "stream" / "events.parquet")
    return patients, wear, events


def make_splits(ids: list[str], seed: int, fracs: dict) -> dict[str, list[str]]:
    rng = np.random.default_rng(seed)
    ids = sorted(ids)
    perm = list(rng.permutation(ids))
    n_tr = int(round(fracs["train"] * len(ids)))
    n_va = int(round(fracs["val"] * len(ids)))
    return {"train": perm[:n_tr], "val": perm[n_tr : n_tr + n_va], "test": perm[n_tr + n_va :]}


@dataclass
class Cohort:
    """All per-patient frames, features, labels and sequence channels in memory."""

    patients: pd.DataFrame
    ehr: pd.DataFrame  # encoded EHR features, indexed by patient_id
    table: pd.DataFrame  # one row per (patient, 5-min step): ids, features, labels
    seq: np.ndarray  # (total_rows, C) sequence channels aligned with `table`
    splits: dict[str, list[str]]
    cutoff: pd.Timestamp

    @property
    def feature_cols(self) -> list[str]:
        return [c for c in self.table.columns if c.startswith(("w_", "t_"))] + list(self.ehr.columns)


def build_cohort(patients: pd.DataFrame, wear: pd.DataFrame, events: pd.DataFrame,
                 splits: dict[str, list[str]] | None = None) -> Cohort:
    """Compute features + labels + sequence channels for every patient and every 5-min step."""
    cfg = get_config()
    dcfg = cfg["dataset"]
    if splits is None:
        splits = make_splits(list(patients.index), cfg["seed"], dcfg["split"])
    t_min, t_max = wear["ts"].min(), wear["ts"].max()
    cutoff = t_min + (t_max - t_min) * (1 - dcfg["temporal_holdout_frac"])
    split_of = {pid: s for s, ids in splits.items() for pid in ids}

    ev_by = dict(tuple(events.groupby("patient_id")))
    tables, seqs = [], []
    for pid, wp in wear.groupby("patient_id", sort=True):
        frame = build_frame(wp, ev_by.get(pid))
        feats = wearable_features(frame)
        lab = labels(frame, horizon=dcfg["horizon_min"] // 5, spike=dcfg["spike_threshold"], hypo=dcfg["hypo_threshold"])
        t = pd.concat([frame[["ts", "cgm"]], feats, lab], axis=1)
        t.insert(0, "patient_id", pid)
        t["row"] = np.arange(len(t))
        t["split"] = split_of.get(pid, "none")
        tables.append(t)
        seqs.append(seq_channels(frame))
    table = pd.concat(tables, ignore_index=True)
    seq = np.concatenate(seqs, axis=0)
    ehr = ehr_feature_matrix(patients)
    log.info("Cohort table: %d rows x %d cols; seq %s", len(table), table.shape[1], seq.shape)
    return Cohort(patients, ehr, table, seq, splits, cutoff)


def sample_index(c: Cohort, split: str, stride_min: int, part: str = "all") -> np.ndarray:
    """Global row indices for a split.

    ``part``: ``all`` | ``pre`` (label window ends before the temporal cut-off) | ``post`` (after it).
    Rows need >= history_hours of history, eligibility (CGM <= 180) and an observed label.
    """
    cfg = get_config()["dataset"]
    t = c.table
    m = (t["split"] == split) & t["eligible"] & t["y_spike"].notna()
    m &= t["row"] >= cfg["history_hours"] * H
    m &= (t["row"] % max(stride_min // 5, 1)) == 0
    horizon = pd.Timedelta(minutes=cfg["horizon_min"])
    if part == "pre":
        m &= t["ts"] + horizon <= c.cutoff
    elif part == "post":
        m &= t["ts"] > c.cutoff
    return np.flatnonzero(m.to_numpy())


def matrix(c: Cohort, idx: np.ndarray, cols: list[str]) -> pd.DataFrame:
    """Feature matrix (wearable/clock columns + joined EHR columns) for the given global rows."""
    t = c.table.iloc[idx]
    w_cols = [x for x in cols if not x.startswith("ehr_")]
    e_cols = [x for x in cols if x.startswith("ehr_")]
    X = t[w_cols].reset_index(drop=True)
    if e_cols:
        E = c.ehr.loc[t["patient_id"].to_numpy(), e_cols].reset_index(drop=True)
        X = pd.concat([X, E], axis=1)
    return X[cols]


def windows(c: Cohort, idx: np.ndarray, length: int) -> np.ndarray:
    """Gather sequence windows (B, length, C) ending at each global row (rows before the patient's
    first row never occur because samples require >= 24 h of history)."""
    offs = np.arange(-length + 1, 1)
    return c.seq[idx[:, None] + offs[None, :]]


def save_splits(splits: dict[str, list[str]], cutoff: pd.Timestamp) -> Path:
    p = path_of("artifacts_dir") / "splits.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump({**splits, "temporal_cutoff": str(cutoff)}, f, indent=1)
    return p


def feature_groups(cols: list[str]) -> dict[str, list[str]]:
    """Column lists for the ablation variants."""
    w = [c for c in cols if c.startswith("w_")]
    t = [c for c in cols if c.startswith("t_")]
    e = [c for c in cols if c.startswith("ehr_")]
    return {"wearable_only": w + t, "ehr_only": e + t, "fused": w + t + e}
