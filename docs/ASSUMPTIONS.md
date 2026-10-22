# Synthetic-data assumptions register

> **SYNTHETIC DATA ONLY: NOT FOR CLINICAL USE.** Synthetic realism is the **main validity risk** of this
> PoC. The models can only learn relationships we wrote into the generator. Every assumption is
> listed here so reviewers can challenge it. Code locations are given in brackets.

## A. EHR cohort (Stream A) [`data_gen/ehr_generator.py`]

| # | Assumption | Value used | Why / caveat |
|---|---|---|---|
| A1 | Age distribution of an Indian T2D clinic cohort | N(50, 11), clipped 25-80 | Roughly matches Indian diabetes registry age profiles. Not fitted to a specific registry |
| A2 | Sex ratio | 55% male | Clinic attendance skew. Unverified |
| A3 | Urban share | 60% | Configurable (`cohort.urban_fraction`) |
| A4 | BMI | N(26, 3.8) + 1.2 if urban + 0.3 x PRS | Indian T2D patients are often "thin-fat": BMI is modest, waist is high |
| A5 | Waist | 40 + 2 x BMI + 5 if male + N(0, 5) | Gives most patients above the South-Asian waist cut-offs (M >= 90, F >= 80 cm) |
| A6 | Family history prevalence | 55% | Strong familial clustering is reported in India. Approximate |
| A7 | Risk-allele frequencies | TCF7L2 0.30, SLC30A8 0.70, KCNQ1 0.55 | Approximate South-Asian frequencies. **Simulated markers, not real genotypes** |
| A8 | PRS | Standardised weighted allele sum + family history + noise | Toy PRS |
| A9 | Duration of diabetes | Gamma(2, 3.5) years, earlier diagnosis with higher PRS | Produces early-onset cases (diagnosed < 40 y) |
| A10 | HbA1c | 7.0 + 0.55 x insulin resistance + 2.2 x (0.85 - beta-cell) + 2.5 x (0.85 - adherence) + noise | Cohort mean ~7.6-8%. Indian clinic means of ~8-8.5% are often reported |
| A11 | Fasting / post-prandial glucose | Linear in HbA1c + noise | Lab variability only |
| A12 | Lipids | Low HDL, high TG (atherogenic dyslipidaemia) | Typical South-Asian pattern |
| A13 | eGFR | Declines with age, duration and HbA1c | Creatinine is back-computed (not CKD-EPI) |
| A14 | Comorbidities | Logistic in age, BMI, duration | Hypertension ~50%, prior CVD ~10% |
| A15 | Medication patterns | Metformin 88% (not if eGFR < 30), SU ~40%, DPP-4i 40%, SGLT2i ~22%, insulin more likely with high HbA1c / long duration; premix 30/70 more common than basal | Reflects common Indian practice (premix use, gliptins). Doses are simplified |
| A16 | Diet | 35% vegetarian; staple rice / wheat / millet | Regional variation is not modelled explicitly |
| A17 | Consent | Every synthetic patient has a *simulated* consent record | Demonstrates consent gating only |

## B. Physiology [`data_gen/physiology.py`]

| # | Assumption | Caveat |
|---|---|---|
| B1 | Extended **Bergman minimal model** (glucose, remote insulin action, plasma insulin) with 1-min Euler steps | Teaching-grade. Not the validated UVA/Padova simulator |
| B2 | Insulin sensitivity SI = 2.4e-4 x exp(-0.45 x insulin-resistance index) x lognormal(0, 0.15) | Order of magnitude typical for T2D. Not individually calibrated to clamps |
| B3 | Endogenous secretion is proportional to glucose above the basal set-point, scaled by beta-cell function (0.15-1.2) | No first/second phase. No incretin effect except via the DPP-4i term |
| B4 | Two-compartment gut (fast k = 0.030/min, slow k = 0.011/min), 65% effective appearance | Meal GI is approximated by the fast/slow split per meal |
| B5 | Basal set-point Gb is **calibrated so simulated mean glucose matches the ADAG eAG of the EHR HbA1c** | This is the main EHR -> signal link. GMI-HbA1c correlation is reported in `data/manifest.json` |
| B6 | Dawn phenomenon: Gaussian rise in set-point centred at 06:30, amplitude 3-22% (higher with HbA1c) | Simplified |
| B7 | Metformin lowers the set-point (Emax 22%, t1/2 5 h). SU raises secretion and adds glucose-independent secretion (t1/2 9 h). DPP-4i boosts meal-time secretion. SGLT2i adds renal excretion above 80 mg/dL scaled by eGFR | Qualitative PK/PD only |
| B8 | Insulin: premix = 30% rapid (ka 0.022) + 70% NPH (ka 0.0055); glargine = slow depot | No dose-response validation |
| B9 | Exercise: insulin-independent uptake (0.008 x intensity x G) plus a 6-h post-exercise sensitivity boost (up to +35%) | Simplified |
| B10 | **Sleep**: each hour of sleep debt (vs a personal need of 5.5-8.5 h) cuts next-day insulin sensitivity by ~7% (cap 28%). Fragmented nights cost 5% more | Direction matches sleep-restriction studies. Magnitude is approximate |
| B11 | **Stress** raises the set-point by up to 10%, raises HR and lowers HRV by up to 35% | Simplified cortisol/sympathetic effect |
| B12 | Counter-regulation below 70 mg/dL | Hypoglycaemia is rare in the cohort (TBR ~0.1%); the hypo head is not validated |

## C. Lifestyle and meals [`data_gen/world.py`, `data_gen/meals.py`]

| # | Assumption |
|---|---|
| C1 | Indian meal library (idli-sambar, poha, dal-chawal, roti-sabzi, biryani, khichdi, millet dishes, chai + biscuits, sweets) with typical home-portion carbs. Choice is weighted by staple and diet |
| C2 | Late dinners: habitual dinner time N(20:54, 0.7 h), +0.3 h urban, +30 min at weekends |
| C3 | Portions scale with sex and BMI and are 10% larger at weekends. Day-to-day jitter is log-normal (sd 0.15) |
| C4 | Meals are logged with a per-patient probability (35-98%); logged carbs carry ~22% estimation error |
| C5 | Medication adherence 45-99% (hidden). Evening doses are slightly less adherent |
| C6 | Morning-walk habit (30-40%) and post-dinner walk (25%). Rural patients are more active |
| C7 | Sleep: ~6.6 h mean, poor nights with probability 2-40% (more with BMI > 30) |
| C8 | Work-day stress episodes with probability 2-80% (higher urban) |

## D. Sensors [`data_gen/world.py::_emit`]

| # | Assumption |
|---|---|
| D1 | CGM = interstitial glucose (8-min first-order lag) x (1 + drift) x (1 + 4% noise) + 3 mg/dL noise, clipped 40-400 |
| D2 | CGM dropouts: ~0.35 episodes/day, mean ~60 min |
| D3 | Compression lows during sleep: ~12% of nights, 20-60 min at 60-80% of true value |
| D4 | Smartwatch off-wrist (charging) 30-75 min on 60% of days |
| D5 | HR/HRV respond to activity, sleep stage, stress, glucose > 180 and last night's sleep. HRV is lower with age and diabetes duration (autonomic) |
| D6 | Sleep stages from a 90-min-cycle hypnogram generator (deep front-loaded, REM back-loaded) |

## E. Labels and evaluation

| # | Assumption |
|---|---|
| E1 | "Spike" = two consecutive CGM readings > 180 mg/dL in the next 120 min. Predictions only while current CGM <= 180 |
| E2 | Labels come from the **observed** (noisy) CGM, not the hidden true glucose, as a real system would |
| E3 | Sustained onset (for lead time) = 2 readings > 180 after >= 30 min with no reading > 180 |

## Known gaps

* No illness, menstrual cycle, alcohol, festivals or fasting (e.g. religious fasts) were modelled.
* No inter-day drift in insulin sensitivity beyond sleep/exercise, and no seasonal effects.
* The same simulator generates training and test data. Real-world transfer is untested.
