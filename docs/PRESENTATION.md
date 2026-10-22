# T2D Digital Twin: presentation summary

> SYNTHETIC DATA ONLY: NOT FOR CLINICAL USE. All results are on simulated patients.

## 1. Problem
* India has one of the world's largest T2D populations. Post-prandial hyperglycemia is common because of
  rice- and wheat-heavy meals, late dinners, a high-waist "thin-fat" phenotype and early onset.
* Clinicians see HbA1c every few months. CGMs and smartwatches stream continuously, but nobody turns the
  two into **timely, explainable, personalised** warnings.

## 2. Our twin, in one sentence
A per-patient Digital Twin that **fuses the EHR with a live wearable/CGM stream** to warn **~45–85 minutes
before** glucose crosses **180 mg/dL**, explains why in plain language, and lets the clinician test
**what-if** interventions on a personalised physiological model.

## 3. Approach
| Step | What we built |
|---|---|
| Data (privacy-safe) | Custom synthetic **Indian T2D EHR** generator (South-Asian BMI/waist cut-offs, diet and staple, premix insulin, gliptins, simulated TCF7L2/SLC30A8/KCNQ1 + PRS). A **physiological world simulator** with Indian meals, dawn phenomenon, exercise, sleep-debt and stress effects, CGM artefacts and dropouts. Its glucose is **calibrated to each patient's HbA1c** (GMI vs HbA1c r = 0.95) |
| Fusion models | LightGBM baseline (118 causal features). **Deep fusion**: GRU over 6 h of multichannel wearable data + EHR MLP, EHR-conditioned cross-attention, gated fusion, heads for spike / hypo / P10-P50-P90 at 4 horizons |
| Twin | Rolling state + **personalised simulator** (EHR prior -> online CGM sync -> 6-hourly calibration) + **what-if engine** |
| Real time | Stream simulator (1x–900x) -> FastAPI ingestion -> twin -> WebSocket -> React dashboard. Live **event injection** |
| Trust | TreeSHAP / Integrated-Gradients factors in plain language, each alert's track record, data-quality and imputation indicators, consent gating, audit trail |

## 4. Results (23 unseen test patients, synthetic)
* ROC-AUC **0.94**, PR-AUC **0.87–0.88** (random = 0.31). Calibrated (Brier 0.09).
* Notification level (≤ 1 false alert/patient-day): **80% of spikes caught, 45 min mean lead** (deep fusion).
  The AMBER watch level flags 98% of spikes ~85 min ahead but is noisier.
* Forecast RMSE at +60 min: 25 mg/dL vs 34 for persistence.
* **Fusion:** no gain in steady-state ranking metrics. **+0.02 PR-AUC at cold start**, and **+5 pts spike detection** at
  the notification operating point. We report both, honestly.
* Robust to CGM noise and dropouts, missing smartwatch data and missing meal logs (≤ 0.02 PR-AUC drop).

## 5. Demo highlights
Cohort triage → twin view with forecast band and countdown → inject a heavy meal and watch RED fire →
"Why this alert?" → what-if: walk now / dinner at 19:00 vs 21:00 / sleep 5 h vs 8 h → acknowledge, note,
audit trail. Script: [DEMO.md](DEMO.md).

## 6. Limitations and next steps
* Synthetic data: models learn our simulator. Not a medical device, and no clinical validation.
* Next: ethics-approved retrospective validation on Indian CGM + EHR, then **federated learning** across
  sites, **ABDM / FHIR R4** integration (FHIR export is ready), a prospective silent trial, and the CDSCO SaMD pathway.
