# Data dictionary

All data is synthetic. Patient IDs are random pseudonyms (`TWN-xxxxxx`) with no link to any person.

## Files (created by `make data`)

| File | Content | Used by models? |
|---|---|---|
| `data/ehr/patients.csv` | Observable EHR (Stream A), one row per patient | Yes |
| `data/ehr/fhir_bundle.json` | FHIR R4 export of the same EHR (Patient, Condition, Observation, MedicationStatement) | No (interoperability demo) |
| `data/ehr/latent_truth.csv` | **Hidden** simulator traits and parameters (adherence, habits, true SI/beta-cell...) | **No.** Used only by the world simulator and tests |
| `data/stream/wearables.parquet` | 5-min device stream (Stream B) + hidden `glucose_true`, `stress_true` | Device columns only. Hidden columns are dropped in `ml.dataset.load_raw` |
| `data/stream/events.parquet` | *Logged* events: meal logs (estimated carbs) and medication intake (smart pill box / connected pen) | Yes |
| `data/stream/events_truth.parquet` | All true events, including unlogged meals and true carbs | No (analysis only) |
| `data/manifest.json` | Generator version, seed, cohort realism summary | No |
| `data/audit.sqlite3` | Audit trail + simulated consent registry (backend) | No |

## Stream A: EHR (`patients.csv`)

| Column | Type / unit | Notes |
|---|---|---|
| `patient_id` | str | Pseudonymous ID |
| `age`, `sex`, `region` | years, M/F, urban/rural | |
| `height_cm`, `weight_kg`, `bmi`, `waist_cm` | cm, kg, kg/m², cm | |
| `bmi_band_sa` | normal / overweight / obese | **South-Asian cut-offs**: 23 and 25 kg/m² |
| `waist_high_sa` | bool | Waist >= 90 cm (M) / >= 80 cm (F) |
| `family_history_dm`, `early_onset` | bool | Early onset = diagnosed before 40 |
| `years_since_dx`, `age_at_dx` | years | |
| `hypertension`, `sbp`, `dbp`, `dyslipidemia`, `prior_cvd`, `ckd_stage` | bool, mmHg, KDIGO G-stage | |
| `hba1c`, `fasting_glucose`, `postprandial_glucose` | %, mg/dL | |
| `total_chol`, `ldl`, `hdl`, `triglycerides` | mg/dL | |
| `egfr`, `creatinine` | mL/min/1.73m², mg/dL | |
| `metformin_mg`, `sulfonylurea_mg` | mg/day | Glimepiride for SU |
| `dpp4`, `sglt2` | bool | Teneligliptin / dapagliflozin as examples |
| `insulin_type`, `insulin_units_day` | none / basal_glargine / premix_30_70, U/day | |
| `snp_tcf7l2`, `snp_slc30a8`, `snp_kcnq1` | 0/1/2 risk alleles | **Simulated** |
| `prs` | z-score | Simulated polygenic risk score |
| `diet`, `staple` | vegetarian / non_vegetarian; rice / wheat / millet | India-specific context |
| `consent_twin_monitoring` | bool | Simulated consent flag |

The model input encoding (`ehr_*` features, one-hot categoricals) comes from `data_gen.ehr_generator.ehr_feature_matrix`.

## Stream B: wearables (`wearables.parquet`, one row per patient per 5 min)

| Column | Unit | Device analogue | Notes |
|---|---|---|---|
| `ts` | timestamp | | End of the 5-min interval |
| `cgm` | mg/dL | CGM (Libre/Dexcom-like) | NaN = dropout. Includes lag, noise, drift and compression artefacts |
| `hr` | bpm | Smartwatch | NaN when off-wrist |
| `hrv_rmssd` | ms | Smartwatch | |
| `steps` | count / 5 min | Smartwatch / phone | |
| `activity` | 0-1 | Intensity (0.03 rest ... 0.5 brisk walk ... 0.8 vigorous) | |
| `sleep_stage` | 0 awake, 1 light, 2 deep, 3 REM | Sleep tracker | |
| `spo2` | % | Smartwatch | |
| `skin_temp` | °C | Smartwatch | |
| `glucose_true`, `stress_true` | | **Hidden ground truth** | Never used as model input |

## Events (`events.parquet`)

| Column | Notes |
|---|---|
| `type` | `meal` or `med` |
| `name`, `label` | Meal key (e.g. `dal_chawal`) / drug (`metformin`, `sulfonylurea`, `dpp4`, `sglt2`, `insulin_premix`, `insulin_basal`) |
| `logged_amount` | Patient-estimated carbs (g) or recorded dose (g metformin, mg SU, tablets, units) |
| `injected` | True for events injected live from the demo control panel |

## Model features (`ml/features.py`)

| Group | Prefix | Examples |
|---|---|---|
| Wearable / CGM / app | `w_` | `w_g_now`, `w_slope_{15,30,60}m`, `w_g_{mean,std,min,max}_{1h,3h,6h,24h}`, `w_cv_24h`, `w_tar_24h`, `w_yday_next2h_max`, `w_min_since_meal`, `w_carbs_{1h,3h,6h,24h}`, `w_cob`, `w_min_since_met`, `w_iob`, `w_steps_{30m,1h,3h,24h}`, `w_active_min_3h`, `w_hr_1h`, `w_hrv_z`, `w_sleep_h_12h`, `w_deep_h_12h`, `w_sleep_debt_h`, `w_valid_1h` (data quality) |
| Clock context | `t_` | `t_tod_sin`, `t_tod_cos`, `t_weekend` |
| Static EHR | `ehr_` | All `patients.csv` items above, encoded |
| Deep sequence | `SEQ_CHANNELS` | 6 h x 5 min x 17 channels: CGM (imputed), CGM-missing mask, steps, activity, HR, log-HRV, wear-missing, asleep/deep/REM, carbs, metformin, SU, tablets, insulin, time of day |

**Imputation**: CGM is forward-filled for up to 60 min, then the trailing 24-h mean is used. A minutes-since-last-reading feature and a missing-mask channel tell the model when it is imputing. The dashboard shows a data-quality indicator.

## Labels (`ml/features.py::labels`)

| Label | Definition |
|---|---|
| `eligible` | Current CGM (imputed, last real reading <= 15 min old) <= 180 mg/dL |
| `y_spike` | Two consecutive CGM readings > 180 within the next 120 min |
| `y_hypo` | Two consecutive CGM readings < 70 within the next 120 min |
| `y_g30..y_g120` | CGM at +30/60/90/120 min |
