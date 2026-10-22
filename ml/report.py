"""Render reports/evaluation_report.md from the computed metrics dictionary (no hand-typed numbers)."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from common import get_config, path_of

NAMES = {
    "deep_fused": "Deep fusion (GRU + EHR cross-attention, gated)", "deep_wearable_only": "Deep, wearable-only",
    "deep_ehr_only": "Deep, EHR-only", "gbm_fused": "LightGBM, fused", "gbm_wearable_only": "LightGBM, wearable-only",
    "gbm_ehr_only": "LightGBM, EHR-only",
}
ORDER = ["gbm_wearable_only", "gbm_ehr_only", "gbm_fused", "deep_wearable_only", "deep_ehr_only", "deep_fused"]


def f(x, d: int = 3) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    return f"{x:.{d}f}"


def write_report(m: dict, path: Path) -> None:
    cfg = get_config()
    R = m["results"]
    serve = m["serving_model"]
    manifest_p = path_of("data_dir") / "manifest.json"
    manifest = json.loads(manifest_p.read_text()) if manifest_p.exists() else {}
    ts = json.loads((path_of("artifacts_dir") / "training_summary.json").read_text())
    L: list[str] = []
    a = L.append
    a("# Evaluation report: T2D Digital Twin (hyperglycemia > 180 mg/dL within 120 min)\n")
    a("> **SYNTHETIC DATA ONLY: NOT FOR CLINICAL USE.** All results below are on simulated patients. They measure")
    a("> how well the models recover structure that *we* put into the simulator. They say nothing about real-world")
    a("> clinical performance.\n")
    a(f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} by `ml/evaluate.py`. Seed {cfg['seed']}._\n")

    s = manifest.get("summary", {})
    a("## 1. Setup\n")
    a(f"* Cohort: {s.get('patients', '?')} synthetic patients x {s.get('days', '?')} days at 5-min resolution "
      f"(mean HbA1c {s.get('mean_hba1c', '?')}%, TIR {s.get('tir_70_180_pct', '?')}%, "
      f"{s.get('spike_onsets_per_patient_day', '?')} sustained spike onsets / patient-day).")
    a(f"* Split **by patient**: {m['train_patients']} train / {m['val_patients']} validation / {m['test_patients']} test. "
      f"**Temporal hold-out**: train patients after {m['temporal_cutoff'][:16]} (last "
      f"{int(cfg['dataset']['temporal_holdout_frac']*100)}% of days). Training rows end their label window before the cut-off.")
    a("* Prediction made every 5 min whenever current CGM <= 180 mg/dL (\"eligible\"). Label = two consecutive CGM readings > 180 "
      "in the next 120 min.")
    a(f"* Alert thresholds are chosen on **validation** patients: AMBER = sample-level sensitivity >= "
      f"{cfg['alerting']['amber_target_sensitivity']}; RED = lowest threshold whose live alert replay gives <= "
      f"{cfg['alerting']['red_max_false_alerts_per_day']} false alert per patient-day. Test patients are never used for tuning. "
      f"Refractory period {cfg['alerting']['refractory_min']} min.")
    vr = {k: R[f"{k}_fused"].get("val_red_replay", {}).get("event_sensitivity") for k in ("deep", "gbm")}
    a(f"* Training wall time (CPU): {ts.get('train_seconds', '?')} s. Model served in the demo: **{serve}_fused**, chosen "
      f"on validation patients by the operational criterion: spikes detected at the RED notification operating point "
      f"(deep {f(vr['deep'], 2)} vs GBM {f(vr['gbm'], 2)}).\n")

    a("## 2. Headline results (test patients, never seen in training)\n")
    a("| Model | ROC-AUC (95% CI) | PR-AUC | Brier | Sens @AMBER | Spec @AMBER | PPV @AMBER |")
    a("|---|---|---|---|---|---|---|")
    for k in ORDER:
        c = R[k]["test"]["classification"]
        ci = c.get("roc_auc_ci")
        ci_txt = f" ({f(ci[0])}-{f(ci[1])})" if ci else ""
        a(f"| {NAMES[k]} | {f(c['roc_auc'])}{ci_txt} | {f(c['pr_auc'])} | {f(c['brier'])} | "
          f"{f(c.get('sensitivity'))} | {f(c.get('specificity'))} | {f(c.get('ppv'))} |")
    prev = R["deep_fused"]["test"]["classification"]["prevalence"]
    a(f"\nPrevalence of the positive class among eligible test rows: {f(prev)} (the PR-AUC of a random classifier). "
      "The CI (fused models) is a patient-level (cluster) bootstrap.\n")

    a("### Episode-level alerting (live replay, test patients)\n")
    a("| Model | Operating point | Spike onsets | Detected (event sensitivity) | Mean / median lead time (min) | Alert precision | False alerts / patient-day |")
    a("|---|---|---|---|---|---|---|")
    for k in ("gbm_fused", "deep_fused", "gbm_wearable_only", "deep_wearable_only"):
        for key, lbl in (("alerts", "AMBER"), ("alerts_red", "RED")):
            al = R[k]["test"].get(key)
            if not al:
                continue
            a(f"| {NAMES[k]} | {lbl} (p >= {f(al['threshold'], 2)}) | {al['onsets']} | {al['detected']} ({f(al['event_sensitivity'], 2)}) | "
              f"{f(al['mean_lead_min'], 0)} / {f(al['median_lead_min'], 0)} | {f(al['alert_precision'], 2)} | "
              f"{f(al['false_alerts_per_patient_day'], 2)} |")
    a("\nLead time = minutes between the first alert in the 120 min before a sustained onset and the onset. "
      "An alert counts as true if an onset follows within 120 min. The AMBER operating point (high sensitivity) "
      "produces several false alerts per patient-day, which is too many for push notifications. The dashboard "
      f"therefore **notifies at {cfg['alerting'].get('notify_level', 'RED')}** and shows AMBER only as a watch "
      "level on the badge and gauge.\n")
    a("![Alert lead time](figures/lead_time.png)\n")

    a("## 3. Ablation: does fusion help?\n")
    a("| Variant | GBM PR-AUC | Deep PR-AUC | GBM ROC-AUC | Deep ROC-AUC | Deep RMSE@60 (mg/dL) |")
    a("|---|---|---|---|---|---|")
    for v in ("wearable_only", "ehr_only", "fused"):
        g, d = R[f"gbm_{v}"]["test"], R[f"deep_{v}"]["test"]
        a(f"| {v.replace('_', ' ')} | {f(g['classification']['pr_auc'])} | {f(d['classification']['pr_auc'])} | "
          f"{f(g['classification']['roc_auc'])} | {f(d['classification']['roc_auc'])} | "
          f"{f(d.get('forecast', {}).get('60', d.get('forecast', {}).get(60, {})).get('rmse'), 1)} |")
    dw, df_ = R["deep_wearable_only"]["test"]["classification"]["pr_auc"], R["deep_fused"]["test"]["classification"]["pr_auc"]
    gw, gf = R["gbm_wearable_only"]["test"]["classification"]["pr_auc"], R["gbm_fused"]["test"]["classification"]["pr_auc"]
    a(f"\n**Fusion gain over wearable-only with full (>= 24 h) history (PR-AUC):** deep {df_ - dw:+.3f}, GBM {gf - gw:+.3f}.\n")

    a("### Cold start: first day of monitoring (6-24 h of history, test patients)\n")
    a("When a patient has just started wearing the devices, 24-h CGM features, yesterday's pattern and the sleep history "
      "are incomplete. The static EHR then has to carry the patient-specific context.\n")
    a("| Variant | GBM PR-AUC | Deep PR-AUC | GBM ROC-AUC | Deep ROC-AUC | Rows |")
    a("|---|---|---|---|---|---|")
    for v in ("wearable_only", "ehr_only", "fused"):
        g, d = R[f"gbm_{v}"].get("cold_start", {}), R[f"deep_{v}"].get("cold_start", {})
        if g and d:
            a(f"| {v.replace('_', ' ')} | {f(g['classification']['pr_auc'])} | {f(d['classification']['pr_auc'])} | "
              f"{f(g['classification']['roc_auc'])} | {f(d['classification']['roc_auc'])} | {g['classification']['n']} |")
    if "cold_start" in R["deep_fused"]:
        cw = R["deep_wearable_only"]["cold_start"]["classification"]["pr_auc"]
        cf = R["deep_fused"]["cold_start"]["classification"]["pr_auc"]
        gcw = R["gbm_wearable_only"]["cold_start"]["classification"]["pr_auc"]
        gcf = R["gbm_fused"]["cold_start"]["classification"]["pr_auc"]
        a(f"\n**Fusion gain at cold start (PR-AUC):** deep {cf - cw:+.3f}, GBM {gcf - gcw:+.3f}.\n")
    rf, rw = R["deep_fused"]["test"].get("alerts_red"), R["deep_wearable_only"]["test"].get("alerts_red")
    if rf and rw:
        a(f"**Fusion at the notification operating point (deep, RED, test):** {f(rf['event_sensitivity'], 2)} of spike onsets "
          f"detected with {f(rf['false_alerts_per_patient_day'], 2)} false alerts/patient-day (fused) vs "
          f"{f(rw['event_sensitivity'], 2)} with {f(rw['false_alerts_per_patient_day'], 2)} (wearable-only). Each RED "
          "threshold was set independently on validation patients to the same false-alert budget.\n")
    a("**Interpretation.** EHR-only models carry no information about the current state, so they learn time-of-day x "
      "patient-control risk. Wearable-only models with a full day of history already encode most of what the EHR says "
      "about glycemic control, because 24 h of CGM is a strong proxy for HbA1c, medication effect and meal habits. "
      "In this simulator the ranking metrics (ROC/PR-AUC) barely move with fusion in the steady state. The gains show up "
      "at cold start and at the high-specificity alerting operating point, where the EHR context helps separate "
      "patients who reliably spike from those who do not. We report both as they are.\n")
    a("![Ablation](figures/ablation.png)\n")
    a("![ROC and PR curves](figures/roc_pr.png)\n")

    a("## 4. Glucose forecast (multi-horizon, all test rows)\n")
    a("| Horizon | Deep P50 RMSE | Deep P50 MAE | GBM RMSE | GBM MAE | Persistence RMSE | Deep P10-P90 coverage (target 0.80) |")
    a("|---|---|---|---|---|---|---|")
    fd, fg = R["deep_fused"]["test"].get("forecast", {}), R["gbm_fused"]["test"].get("forecast", {})
    for h in (30, 60, 90, 120):
        d, g = fd.get(h, fd.get(str(h), {})), fg.get(h, fg.get(str(h), {}))
        a(f"| +{h} min | {f(d.get('rmse'), 1)} | {f(d.get('mae'), 1)} | {f(g.get('rmse'), 1)} | {f(g.get('mae'), 1)} | "
          f"{f(d.get('persistence_rmse'), 1)} | {f(d.get('coverage_p10_p90'), 2)} |")
    a("\n![Forecast example](figures/forecast_example.png)\n")

    a("## 5. Calibration\n")
    a("Both fused models are isotonic-calibrated on validation patients. Brier scores are in section 2.\n")
    a("![Reliability](figures/reliability.png)\n")

    a("## 6. Temporal hold-out (train patients, future days)\n")
    a("| Model | ROC-AUC | PR-AUC | Brier | False alerts / patient-day | Mean lead (min) |")
    a("|---|---|---|---|---|---|")
    for k in ORDER:
        if "temporal" in R[k]:
            c, al = R[k]["temporal"]["classification"], R[k]["temporal"]["alerts"]
            a(f"| {NAMES[k]} | {f(c['roc_auc'])} | {f(c['pr_auc'])} | {f(c['brier'])} | "
              f"{f(al['false_alerts_per_patient_day'], 2)} | {f(al['mean_lead_min'], 0)} |")
    a("")

    hy = R["deep_fused"]["test"].get("hypo")
    if hy:
        a("## 7. Secondary target: hypoglycemia (< 70 mg/dL within 120 min)\n")
        a(f"Deep fused hypo head on test: ROC-AUC {f(hy.get('roc_auc'))}, PR-AUC {f(hy.get('pr_auc'))}, with only "
          f"**{hy.get('positives')} positive rows** (prevalence {f(hy.get('prevalence'), 4)}). The synthetic cohort has very "
          "little hypoglycemia, so this estimate is unreliable and the dashboard only shows the hypo flag as advisory.\n")

    a("## 8. Fairness (test patients, by subgroup)\n")
    a(f"Only {m['test_patients']} test patients, so subgroup estimates are noisy. Treat differences as hypotheses, not findings.\n")
    a("Sensitivity and false alerts (FA/day) are measured at the AMBER threshold.\n")
    a("| Attribute | Group | Patients | Prevalence | Deep ROC-AUC | Deep PR-AUC | Deep sens | Deep FA/day | GBM PR-AUC |")
    a("|---|---|---|---|---|---|---|---|---|")
    for attr, groups in m["fairness"].items():
        for lvl, r in groups.items():
            d, g = r["deep_fused"], r["gbm_fused"]
            a(f"| {attr} | {lvl} | {d['patients']} | {f(d['prevalence'], 2)} | {f(d['roc_auc'])} | {f(d['pr_auc'])} | "
              f"{f(d['sensitivity'], 2)} | {f(d['false_alerts_per_patient_day'], 2)} | {f(g['pr_auc'])} |")
    a("")

    if m.get("robustness"):
        a("## 9. Robustness to sensor problems (test patients)\n")
        a("Inputs are perturbed and labels still come from the original CGM. The first row is the unperturbed test set. "
          "Sensitivity and FA/day are measured at the AMBER threshold.\n")
        a("| Perturbation | Deep fused PR-AUC | Deep wearable-only PR-AUC | GBM fused PR-AUC | GBM wearable-only PR-AUC | "
          "Deep fused sens | Deep fused FA/day | Deep fused RMSE@60 |")
        a("|---|---|---|---|---|---|---|---|")
        t = {k: R[k]["test"] for k in ("deep_fused", "deep_wearable_only", "gbm_fused", "gbm_wearable_only")}
        fc = t["deep_fused"].get("forecast", {})
        a(f"| none | {f(t['deep_fused']['classification']['pr_auc'])} | {f(t['deep_wearable_only']['classification']['pr_auc'])} | "
          f"{f(t['gbm_fused']['classification']['pr_auc'])} | {f(t['gbm_wearable_only']['classification']['pr_auc'])} | "
          f"{f(t['deep_fused']['classification'].get('sensitivity'), 2)} | {f(t['deep_fused']['alerts']['false_alerts_per_patient_day'], 2)} | "
          f"{f(fc.get(60, fc.get('60', {})).get('rmse'), 1)} |")
        for kind, r in m["robustness"].items():
            d = r["deep_fused"]
            a(f"| {kind} | {f(d['pr_auc'])} | {f(r['deep_wearable_only']['pr_auc'])} | {f(r['gbm_fused']['pr_auc'])} | "
              f"{f(r['gbm_wearable_only']['pr_auc'])} | {f(d['sensitivity'], 2)} | {f(d['false_alerts_per_patient_day'], 2)} | "
              f"{f(d['rmse_60'], 1)} |")
        a("\n* `cgm_noise_x3`: extra 8% multiplicative + 6 mg/dL additive noise. `cgm_dropout_30pct`: 15% random loss plus a 3-h "
          "gap per day. `wearable_missing_50pct`: half of all smartwatch hours missing. `no_meal_logs`: the patient logs no meals.\n")

    a("## 10. Most important features (GBM fused, gain)\n")
    a("| Feature | Share of gain |")
    a("|---|---|")
    for k, v in m["gbm_importance"][:15]:
        a(f"| `{k}` | {f(v)} |")
    a("\n![Feature importance](figures/feature_importance.png)\n")

    a("## 11. Honest limitations of these numbers\n")
    a("* The simulator generates both the inputs and the labels, so the models can learn the simulator's own rules. "
      "Real-world performance will be lower.")
    a("* Many spikes are driven by meals that have **not happened yet** at prediction time. Those are only predictable from "
      "habit (yesterday's pattern, time of day), which caps achievable precision. That is realistic.")
    a("* The test set is small at the patient level. Use the bootstrap CIs.")
    a("* Hypoglycemia is rare in the synthetic cohort, so the hypo head is not validated.")
    a("* Thresholds and calibration come from simulated validation patients. A real deployment would need site-specific "
      "recalibration and prospective validation.")
    path.write_text("\n".join(L), encoding="utf-8")
