"""Evaluation: metrics, ablations, calibration, lead time, fairness, robustness -> reports/.

Every number in reports/evaluation_report.md is computed here from held-out data. Nothing is
hand-written.

    python -m ml.evaluate          # rebuilds the cohort and evaluates saved artifacts
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import precision_recall_curve, roc_auc_score, roc_curve  # noqa: E402

from common import get_config, get_logger, path_of  # noqa: E402
from ml.alerting import choose_thresholds, simulate_alerts  # noqa: E402
from ml.dataset import Cohort, build_cohort, load_raw, sample_index  # noqa: E402
from ml.deep import DeepBundle  # noqa: E402
from ml.gbm import HORIZONS, GBMModel  # noqa: E402
from ml.metrics import bootstrap_ci, classification, interval_coverage, regression, reliability  # noqa: E402
from ml.predict import predict_rows  # noqa: E402

log = get_logger("ml.evaluate")
VARIANTS = ("wearable_only", "ehr_only", "fused")
PALETTE = {"deep": "#0072B2", "gbm": "#E69F00", "persist": "#999999"}  # Okabe-Ito (colour-blind safe)
LINESTYLE = {"fused": "-", "wearable_only": "--", "ehr_only": ":"}


def load_models() -> dict[str, GBMModel | DeepBundle]:
    art = path_of("artifacts_dir")
    models: dict[str, GBMModel | DeepBundle] = {}
    for v in VARIANTS:
        models[f"gbm_{v}"] = GBMModel.load(art / f"gbm_{v}.pkl")
        models[f"deep_{v}"] = DeepBundle.load(art / f"deep_{v}.pt")
    return models


def _rows(c: Cohort, split: str, part: str = "all", stride: int = 1) -> np.ndarray:
    """All 5-min rows (eligible or not) with >= 24 h history for a split/part.

    ``part="cold"`` instead selects each patient's *first day* (6-24 h of history): a cold-start
    setting where 24-h wearable features are incomplete and the EHR has to carry more weight.
    """
    t = c.table
    h = get_config()["dataset"]["history_hours"] * 12
    m = t["split"] == split
    if part == "cold":
        m &= (t["row"] >= 72) & (t["row"] < h)
    else:
        m &= t["row"] >= h
    if part == "post":
        m &= t["ts"] > c.cutoff
    if stride > 1:
        m &= t["row"] % stride == 0
    return np.flatnonzero(m.to_numpy())


def _replay(t: pd.DataFrame, p: np.ndarray, thr: float, refractory: int) -> tuple[dict, list[int]]:
    """Aggregate the live alert replay over all patients in ``t`` at one threshold."""
    agg = {"alerts": 0, "true_alerts": 0, "false_alerts": 0, "onsets": 0, "detected": 0, "pred_days": 0.0}
    leads: list[int] = []
    pid = t["patient_id"].to_numpy()
    elig = t["eligible"].to_numpy()
    cgm = t["cgm"].to_numpy()
    for u in np.unique(pid):
        m = pid == u
        r = simulate_alerts(np.where(elig[m], p[m], np.nan), elig[m], cgm[m], thr, refractory)
        for k in agg:
            agg[k] += r[k]
        leads += r["lead_times"]
    out = {
        **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in agg.items()},
        "threshold": thr,
        "event_sensitivity": agg["detected"] / max(agg["onsets"], 1),
        "alert_precision": agg["true_alerts"] / max(agg["alerts"], 1),
        "false_alerts_per_patient_day": agg["false_alerts"] / max(agg["pred_days"], 1e-9),
        "mean_lead_min": float(np.mean(leads)) if leads else float("nan"),
        "median_lead_min": float(np.median(leads)) if leads else float("nan"),
        "patients": int(len(np.unique(pid))),
    }
    return out, leads


def _eval_set(c: Cohort, rows: np.ndarray, pred: dict, thr: dict, refractory: int, ci: bool = False) -> dict:
    """Sample-level + episode-level metrics on a set of contiguous patient rows."""
    t = c.table.iloc[rows]
    p = pred["spike"]
    elig = t["eligible"].to_numpy() & t["y_spike"].notna().to_numpy()
    y = t["y_spike"].to_numpy()
    res = {"classification": classification(y[elig], p[elig], thr["amber"])}
    if ci:
        lo, hi = bootstrap_ci(y[elig].astype(int), p[elig], t["patient_id"].to_numpy()[elig], roc_auc_score, n_boot=200)
        res["classification"]["roc_auc_ci"] = [lo, hi]
    # episode-level alert replay per patient, at both operating points
    for key, level in (("alerts", "amber"), ("alerts_red", "red")):
        res[key], leads = _replay(t, p, thr[level], refractory)
        if key == "alerts":
            res["lead_times"] = leads
    # glucose forecast on all rows
    if pred.get("p50") is not None:
        g_now = t["g_now"].to_numpy()
        reg = {}
        for k, h in enumerate(HORIZONS):
            yt = t[f"y_g{h}"].to_numpy()
            reg[h] = {**regression(yt, pred["p50"][:, k]), "persistence_rmse": regression(yt, g_now)["rmse"],
                      "coverage_p10_p90": interval_coverage(yt, pred["p10"][:, k], pred["p90"][:, k])}
        res["forecast"] = reg
    if pred.get("hypo") is not None:
        yh = t["y_hypo"].to_numpy()
        mh = ~np.isnan(yh)
        res["hypo"] = {**classification(yh[mh], pred["hypo"][mh]), "positives": int(np.nansum(yh[mh]))}
    return res


# ----------------------------------------------------------------------------------------------
# robustness
# ----------------------------------------------------------------------------------------------
def _perturb(wear: pd.DataFrame, events: pd.DataFrame, kind: str, rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    w = wear.copy()
    e = events.copy()
    if kind == "cgm_noise_x3":
        w["cgm"] = (w["cgm"] * (1 + rng.normal(0, 0.08, len(w))) + rng.normal(0, 6, len(w))).clip(40, 400).round()
    elif kind == "cgm_dropout_30pct":
        drop = rng.random(len(w)) < 0.15
        # plus one 3-h gap per patient-day
        k = np.arange(len(w)) % 288
        start = rng.integers(0, 288 - 36, len(w) // 288 + 1)
        gap = (k >= np.repeat(start, 288)[: len(w)]) & (k < np.repeat(start, 288)[: len(w)] + 36)
        w.loc[drop | gap, "cgm"] = np.nan
    elif kind == "wearable_missing_50pct":
        blocks = np.repeat(rng.random(len(w) // 12 + 1) < 0.5, 12)[: len(w)]
        w.loc[blocks, ["hr", "hrv_rmssd", "steps", "activity", "spo2", "skin_temp"]] = np.nan
    elif kind == "no_meal_logs":
        e = e[e["type"] != "meal"]
    return w, e


def robustness(c: Cohort, models: dict, thresholds: dict, refractory: int) -> dict:
    patients, wear, events = load_raw()
    test_ids = c.splits["test"]
    w0 = wear[wear["patient_id"].isin(test_ids)]
    e0 = events[events["patient_id"].isin(test_ids)]
    rng = np.random.default_rng(7)
    base = c.table[c.table["split"] == "test"][["patient_id", "row", "y_spike", "y_g30", "y_g60", "y_g90", "y_g120", "cgm"]]
    out = {}
    for kind in ("cgm_noise_x3", "cgm_dropout_30pct", "wearable_missing_50pct", "no_meal_logs"):
        w, e = _perturb(w0, e0, kind, rng)
        cc = build_cohort(patients.loc[test_ids], w, e, splits={"test": test_ids})
        # labels always come from the *original* CGM (ground truth is unaffected by sensor problems)
        lab = base.set_index(["patient_id", "row"])
        key = pd.MultiIndex.from_frame(cc.table[["patient_id", "row"]])
        for col in ("y_spike", "y_g30", "y_g60", "y_g90", "y_g120"):
            cc.table[col] = lab[col].reindex(key).to_numpy()
        cc.table["cgm"] = lab["cgm"].reindex(key).to_numpy()
        rows = _rows(cc, "test")  # full 5-min resolution (the alert replay assumes 5-min spacing)
        out[kind] = {}
        for name in ("deep_fused", "deep_wearable_only", "gbm_fused", "gbm_wearable_only"):
            pred = predict_rows(models[name], cc, rows)
            r = _eval_set(cc, rows, pred, thresholds[name], refractory)
            out[kind][name] = {
                "roc_auc": r["classification"]["roc_auc"], "pr_auc": r["classification"]["pr_auc"],
                "sensitivity": r["classification"]["sensitivity"],
                "false_alerts_per_patient_day": r["alerts"]["false_alerts_per_patient_day"],
                "rmse_60": r.get("forecast", {}).get(60, {}).get("rmse", float("nan")),
            }
        log.info("Robustness %s: %s", kind, out[kind])
    return out


# ----------------------------------------------------------------------------------------------
# fairness
# ----------------------------------------------------------------------------------------------
def subgroups(patients: pd.DataFrame) -> dict[str, pd.Series]:
    age = pd.cut(patients["age"], [0, 44, 59, 200], labels=["<45", "45-59", ">=60"]).astype(str)
    return {"age_group": age, "sex": patients["sex"], "bmi_band_sa": patients["bmi_band_sa"], "region": patients["region"]}


def fairness(c: Cohort, rows: np.ndarray, preds: dict, thresholds: dict, refractory: int) -> dict:
    t = c.table.iloc[rows]
    out: dict = {}
    for attr, ser in subgroups(c.patients).items():
        out[attr] = {}
        g = ser.reindex(t["patient_id"]).to_numpy()
        for level in sorted(pd.unique(g)):
            m = g == level
            out[attr][level] = {}
            for name in ("deep_fused", "gbm_fused"):
                sub = {k: (v[m] if isinstance(v, np.ndarray) else v) for k, v in preds[name].items()}
                r = _eval_set(c, rows[m], sub, thresholds[name], refractory)
                out[attr][level][name] = {
                    "patients": r["alerts"]["patients"], "roc_auc": r["classification"]["roc_auc"],
                    "pr_auc": r["classification"]["pr_auc"], "sensitivity": r["classification"].get("sensitivity"),
                    "false_alerts_per_patient_day": r["alerts"]["false_alerts_per_patient_day"],
                    "prevalence": r["classification"]["prevalence"],
                }
    return out


# ----------------------------------------------------------------------------------------------
# plots
# ----------------------------------------------------------------------------------------------
def _style(ax) -> None:
    ax.grid(alpha=0.25)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)


def plot_curves(c: Cohort, rows: np.ndarray, preds: dict, fig_dir: Path) -> None:
    t = c.table.iloc[rows]
    elig = t["eligible"].to_numpy() & t["y_spike"].notna().to_numpy()
    y = t["y_spike"].to_numpy()[elig]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    for name, pr in preds.items():
        fam, var = name.split("_", 1)
        p = pr["spike"][elig]
        fpr, tpr, _ = roc_curve(y, p)
        prec, rec, _ = precision_recall_curve(y, p)
        kw = dict(color=PALETTE[fam], linestyle=LINESTYLE[var], lw=1.8 if var == "fused" else 1.3, label=name)
        axes[0].plot(fpr, tpr, **kw)
        axes[1].plot(rec, prec, **kw)
    axes[0].plot([0, 1], [0, 1], color="#bbbbbb", lw=1)
    axes[0].set(xlabel="False positive rate", ylabel="True positive rate", title="ROC: spike within 120 min (test patients)")
    axes[1].axhline(y.mean(), color="#bbbbbb", lw=1)
    axes[1].set(xlabel="Recall", ylabel="Precision", title="Precision-recall (test patients)")
    for ax in axes:
        _style(ax)
    axes[1].legend(fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(fig_dir / "roc_pr.png", dpi=130)
    plt.close(fig)


def plot_reliability(c: Cohort, rows: np.ndarray, preds: dict, fig_dir: Path) -> dict:
    t = c.table.iloc[rows]
    elig = t["eligible"].to_numpy() & t["y_spike"].notna().to_numpy()
    y = t["y_spike"].to_numpy()[elig]
    fig, ax = plt.subplots(figsize=(5, 4.6))
    ax.plot([0, 1], [0, 1], color="#bbbbbb", lw=1, label="perfect")
    out = {}
    for name in ("deep_fused", "gbm_fused"):
        rel = reliability(y, preds[name]["spike"][elig])
        out[name] = rel
        fam = name.split("_")[0]
        ax.plot([r["pred"] for r in rel], [r["obs"] for r in rel], marker="o" if fam == "deep" else "s",
                color=PALETTE[fam], label=name)
    ax.set(xlabel="Predicted probability", ylabel="Observed frequency", title="Reliability (test patients)")
    _style(ax)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(fig_dir / "reliability.png", dpi=130)
    plt.close(fig)
    return out


def plot_ablation(results: dict, fig_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 3.8))
    x = np.arange(len(VARIANTS))
    for k, fam in enumerate(("gbm", "deep")):
        vals = [results[f"{fam}_{v}"]["test"]["classification"]["pr_auc"] for v in VARIANTS]
        bars = ax.bar(x + (k - 0.5) * 0.38, vals, 0.36, color=PALETTE[fam], label=fam.upper(),
                      hatch="//" if fam == "gbm" else None, edgecolor="white")
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.01, f"{v:.3f}", ha="center", fontsize=8)
    ax.set_xticks(x, [v.replace("_", " ") for v in VARIANTS])
    ax.set(ylabel="PR-AUC (test patients)", title="Ablation: wearable-only vs EHR-only vs fused", ylim=(0, 1))
    _style(ax)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(fig_dir / "ablation.png", dpi=130)
    plt.close(fig)


def plot_lead_times(leads: list[int], fig_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(6, 3.6))
    ax.hist(leads, bins=np.arange(0, 125, 5), color=PALETTE["deep"], edgecolor="white")
    if leads:
        ax.axvline(np.mean(leads), color="#D55E00", lw=2, linestyle="--", label=f"mean {np.mean(leads):.0f} min")
    ax.set(xlabel="Lead time before spike onset (min)", ylabel="Detected onsets", title="Alert lead time (deep fused, test)")
    _style(ax)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(fig_dir / "lead_time.png", dpi=130)
    plt.close(fig)


def plot_forecast_example(c: Cohort, rows: np.ndarray, pred: dict, thr: dict, fig_dir: Path) -> None:
    t = c.table.iloc[rows].reset_index(drop=True)
    pid = t["patient_id"].iloc[0]
    m = (t["patient_id"] == pid).to_numpy()
    tt = t[m]
    sl = slice(288 * 3, 288 * 4 + 144)  # ~1.5 days
    ts = tt["ts"].to_numpy()[sl]
    k = 1  # +60 min
    p50 = pred["p50"][m][sl, k]
    p10, p90 = pred["p10"][m][sl, k], pred["p90"][m][sl, k]
    tgt = ts + np.timedelta64(60, "m")
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 5.5), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})
    a1.axhspan(70, 180, color="#009E73", alpha=0.08, label="target 70-180")
    a1.plot(ts, c.table["cgm"].to_numpy()[rows][m][sl], color="#222222", lw=1.2, label="CGM (observed)")
    a1.fill_between(tgt, p10, p90, color=PALETTE["deep"], alpha=0.2, label="P10-P90 forecast (+60 min)")
    a1.plot(tgt, p50, color=PALETTE["deep"], lw=1.2, label="P50 forecast (+60 min)")
    a1.axhline(180, color="#D55E00", lw=1, linestyle="--")
    a1.set(ylabel="mg/dL", title=f"Test patient {pid}: forecast vs observed")
    a1.legend(fontsize=8, frameon=False, ncol=4)
    risk = np.where(tt["eligible"].to_numpy()[sl], pred["spike"][m][sl], np.nan)
    a2.plot(ts, risk, color=PALETTE["deep"], lw=1.2)
    a2.axhline(thr["amber"], color="#E69F00", linestyle="--", lw=1, label="AMBER")
    a2.axhline(thr["red"], color="#D55E00", linestyle="--", lw=1, label="RED")
    a2.set(ylabel="P(spike <=120 min)", ylim=(0, 1))
    a2.legend(fontsize=8, frameon=False)
    for ax in (a1, a2):
        _style(ax)
    fig.tight_layout()
    fig.savefig(fig_dir / "forecast_example.png", dpi=130)
    plt.close(fig)


def plot_importance(model: GBMModel, fig_dir: Path, top: int = 20) -> list[tuple[str, float]]:
    imp = pd.Series(model.clf.booster_.feature_importance("gain"), index=model.columns).sort_values(ascending=False)
    imp = imp / imp.sum()
    top_imp = imp.head(top)[::-1]
    fig, ax = plt.subplots(figsize=(7, 6))
    colors = [PALETTE["gbm"] if n.startswith("ehr_") else PALETTE["deep"] for n in top_imp.index]
    ax.barh(top_imp.index, top_imp.values, color=colors)
    ax.set(xlabel="Share of total gain", title="GBM fused: top features (blue = wearable, orange = EHR)")
    _style(ax)
    fig.tight_layout()
    fig.savefig(fig_dir / "feature_importance.png", dpi=130)
    plt.close(fig)
    return [(k, round(float(v), 4)) for k, v in imp.head(top).items()]


# ----------------------------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------------------------
def evaluate(c: Cohort | None = None, fast: bool = False) -> dict:
    cfg = get_config()
    t0 = time.time()
    if c is None:
        c = build_cohort(*load_raw(), splits=_load_splits())
    models = load_models()
    rep_dir = path_of("reports_dir")
    fig_dir = rep_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    acfg = cfg["alerting"]
    refractory = acfg["refractory_min"] // 5

    va = sample_index(c, "val", cfg["dataset"]["train_stride_min"], "all")
    yva = c.table["y_spike"].to_numpy()[va]
    test_rows = _rows(c, "test")
    temp_rows = _rows(c, "train", "post")
    cold_rows = _rows(c, "test", "cold")
    results: dict = {}
    thresholds: dict = {}
    preds_test: dict = {}
    val_rows = _rows(c, "val")
    val_red_replay: dict = {}
    for name, m in models.items():
        pv = predict_rows(m, c, va)["spike"]
        thresholds[name] = choose_thresholds(yva, pv, acfg["amber_target_sensitivity"], acfg["red_target_precision"])
        # RED: lowest threshold whose live-replay false-alert rate on VALIDATION patients is within budget
        pv_all = predict_rows(m, c, val_rows)["spike"]
        t_val = c.table.iloc[val_rows]
        red, val_red = None, None
        for thr in np.arange(thresholds[name]["amber"], 0.99, 0.025):
            rep = _replay(t_val, pv_all, float(thr), refractory)[0]
            if rep["false_alerts_per_patient_day"] <= acfg["red_max_false_alerts_per_day"]:
                red, val_red = float(thr), rep
                break
        thresholds[name]["red"] = round(red if red is not None else 0.95, 4)
        val_red_replay[name] = val_red or _replay(t_val, pv_all, 0.95, refractory)[0]
        val_cls = classification(yva, pv)
        pt = predict_rows(m, c, test_rows)
        preds_test[name] = pt
        res = {"val": val_cls, "val_red_replay": val_red_replay[name], "thresholds": thresholds[name],
               "test": _eval_set(c, test_rows, pt, thresholds[name], refractory, ci=name.endswith("fused"))}
        pc = predict_rows(m, c, cold_rows)
        res["cold_start"] = _eval_set(c, cold_rows, pc, thresholds[name], refractory)
        if name.endswith("fused"):
            ptmp = predict_rows(m, c, temp_rows)
            res["temporal"] = _eval_set(c, temp_rows, ptmp, thresholds[name], refractory)
        results[name] = res
        log.info("%s: test ROC-AUC %.3f PR-AUC %.3f | val PR-AUC %.3f", name, res["test"]["classification"]["roc_auc"],
                 res["test"]["classification"]["pr_auc"], val_cls["pr_auc"])

    serving_choice = cfg["serving"]["model"]
    if serving_choice == "auto":
        # operational criterion on VALIDATION patients: detected spikes at the RED (notification) operating point
        sens = {k: results[f"{k}_fused"]["val_red_replay"]["event_sensitivity"] for k in ("deep", "gbm")}
        serving_choice = "deep" if sens["deep"] >= sens["gbm"] else "gbm"
        log.info("Serving choice by validation event sensitivity at RED: %s -> %s", sens, serving_choice)

    fair = fairness(c, test_rows, {k: preds_test[k] for k in ("deep_fused", "gbm_fused")}, thresholds, refractory)
    robust = robustness(c, models, thresholds, refractory) if not fast else {}

    plot_curves(c, test_rows, preds_test, fig_dir)
    rel = plot_reliability(c, test_rows, preds_test, fig_dir)
    plot_ablation(results, fig_dir)
    plot_lead_times(results[f"{serving_choice}_fused"]["test"]["lead_times"], fig_dir)
    plot_forecast_example(c, test_rows, preds_test["deep_fused"], thresholds["deep_fused"], fig_dir)
    importance = plot_importance(models["gbm_fused"], fig_dir)

    for r in results.values():
        for s in ("test", "temporal", "cold_start"):
            if s in r:
                r[s].pop("lead_times", None)
    metrics = {"results": results, "fairness": fair, "robustness": robust, "reliability": rel,
               "serving_model": serving_choice, "gbm_importance": importance,
               "test_patients": len(c.splits["test"]), "val_patients": len(c.splits["val"]),
               "train_patients": len(c.splits["train"]), "temporal_cutoff": str(c.cutoff)}
    with open(rep_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=1, default=float)
    serving = {"model": serving_choice, "thresholds": thresholds, "refractory_min": acfg["refractory_min"],
               "notify_level": acfg.get("notify_level", "RED"),
               "test_summary": {k: {"roc_auc": v["test"]["classification"]["roc_auc"], "pr_auc": v["test"]["classification"]["pr_auc"]}
                                for k, v in results.items()}}
    with open(path_of("artifacts_dir") / "serving.json", "w", encoding="utf-8") as f:
        json.dump(serving, f, indent=1)

    from ml.report import write_report

    write_report(metrics, rep_dir / "evaluation_report.md")
    log.info("Evaluation done in %.0fs -> %s", time.time() - t0, rep_dir)
    return metrics


def _load_splits() -> dict[str, list[str]]:
    with open(path_of("artifacts_dir") / "splits.json", encoding="utf-8") as f:
        s = json.load(f)
    return {k: s[k] for k in ("train", "val", "test")}


if __name__ == "__main__":
    evaluate()
