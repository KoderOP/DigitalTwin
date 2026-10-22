# PLAN: T2D Digital Twin PoC (India context)

> SYNTHETIC DATA ONLY: NOT FOR CLINICAL USE.

## Goal
A per-patient Digital Twin for Type 2 Diabetes that fuses a static (EHR) stream with a live
wearable/CGM stream. Every 5 simulated minutes it predicts whether glucose will go above 180 mg/dL
in the next 120 minutes. It also gives a multi-horizon glucose forecast, an explanation, and a
what-if simulation, all shown on a live clinician dashboard.

## Key design decisions (defaults, documented in docs/ and README)
| Topic | Decision |
|---|---|
| Python | 3.12 venv (3.11+ supported); CPU-only torch |
| Task runner | `Makefile` + cross-platform `tasks.py` (Windows has no `make` by default) |
| Cohort | 150 virtual patients x 30 days at 5-min resolution (configurable 100-300 x 30-60) |
| World simulator | One vectorised Bergman-minimal-model engine (1-min Euler) used for batch data **and** the live demo stream, so injected events have real physiological effects |
| Label | "Spike onset": at a time when CGM <= 180, two consecutive CGM readings > 180 in (0, 120] min |
| Splits | By patient 70/15/15 (train/val/test) + temporal hold-out (last 20% of days of train patients) + cold-start evaluation |
| Baseline | LightGBM on engineered features, isotonic-calibrated |
| Main model | PyTorch: GRU over 6 h (pooled to 10-min steps for CPU budget) + EHR MLP, EHR-conditioned cross-attention + gated fusion; heads for spike, hypo, quantiles at +30/60/90/120. TCN encoder available via config |
| Ablations | wearable-only / EHR-only / fused for both GBM and deep model |
| Alerting | AMBER = watch level (validation sensitivity 0.8); RED = notification level (≤ 1 false alert/patient-day in validation replay); served model chosen on validation by spikes detected at RED |
| Explainability | TreeSHAP (GBM) / Integrated Gradients (deep), grouped into plain-language factors |
| Twin | Profile + rolling buffer + personalised simulator (EHR prior + online observer + SI/Gb calibration) + what-if |
| Backend | FastAPI + WebSocket; in-process or external stream; SQLite audit + simulated consent |
| Frontend | React + Vite + TS + Tailwind + Recharts, served by FastAPI after build |

## Phases
- [x] **Phase 0**: plan, scaffold, config, environment
- [x] **Phase 1**: data generators (EHR, physiology, world, sensors, FHIR export, Synthea / open-CGM / MIMIC adapters)
- [x] **Phase 2**: dataset builder, causal features, labels, LightGBM baseline + ablations
- [x] **Phase 3**: deep fusion model, training, evaluation, `reports/evaluation_report.md`
- [x] **Phase 4**: twin object, personalised simulator, what-if engine
- [x] **Phase 5**: backend streaming, ingestion, inference loop, WebSocket, audit log, consent
- [x] **Phase 6**: dashboard
- [x] **Phase 7**: docs, tests (pytest 22 + vitest 8), Docker

## Decisions changed during execution (and why)
* The GRU at 5-min resolution was ~90 s/epoch on the laptop CPU. A dilated TCN was *slower* on this CPU, so we
  average-pool the window to 10-min steps (hidden 48) and use a 45-min training stride. Training is ~6 min.
* With RED defined as "PPV ≥ 0.7", RED collapsed onto AMBER and gave ~4.4 false alerts/patient-day. RED is
  now set on validation by a false-alert budget. This exposed that the deep model detects many more spikes
  at that budget than the GBM, so the served model is chosen by that operational criterion.
* Fusion showed no steady-state ranking gain. We added a cold-start evaluation and operating-point
  comparison instead of tuning towards a desired result.
