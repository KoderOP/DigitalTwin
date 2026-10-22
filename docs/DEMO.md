# 5-minute demo script

**Setup (before the audience arrives):** `make demo` (or `python tasks.py demo`) and open
http://127.0.0.1:8000. The engine warms up 12 held-out test patients over 14 simulated days and starts
the live clock at **17:30**, just before Indian dinner time. Keep speed at **60x** (one 5-min tick
every 5 s). Click **Reset** if you need a fresh start.

> Say it once at the start: *"Everything you see is synthetic. These are virtual patients, and the
> banner and footer say so. This is not a medical device."*

---

### 0:00 – 0:40 | The problem and the twin
* "Type 2 diabetes affects more than 100 million people in India. Post-meal spikes above 180 mg/dL
  drive complications, and late, rice-heavy dinners make them common."
* "Each patient here has a **digital twin**. It fuses the static EHR (HbA1c, medications, comorbidities,
  simulated risk SNPs, diet and staple) with a live wearable stream (CGM every 5 min, heart rate, HRV,
  sleep stages, steps). Every 5 minutes it predicts whether glucose will cross 180 mg/dL in the next
  **2 hours**."

### 0:40 – 1:20 | Cohort view (left)
* Patients are sorted by risk. Each badge has a **shape and a word as well as a colour**
  (✓ GREEN, ▲ AMBER, ⬣ RED, ⬆ HIGH NOW), so it stays readable for colour-blind users.
* Show search and the level filter. Point at the trend arrows, the "~X min" countdowns and the
  data-quality icons.
* Click the highest-risk patient.

### 1:20 – 2:20 | Twin view
* **Header**: pseudonymous ID, age/sex, T2D duration, HbA1c, South-Asian BMI band, medications,
  comorbidities, diet/staple, consent (simulated), twin calibration.
* **Live CGM chart**: the last 12 h, the 2-h forecast (median plus P10–P90 band), the 70–180 target
  band, ▲ logged meals, ◆ medication intake and ! alerts. Under it is the **risk-over-time** strip:
  *"Look where risk crossed AMBER. That was well before the glucose rose."*
* **Risk gauge**: calibrated probability, level and the "Predicted spike in ~X min" countdown.
* **Wearable panels** on the same time axis: sleep hypnogram, HR/HRV, steps.
* **Why this alert?**: plain-language factors such as *"Usual pattern at this time: yesterday it peaked at
  246 mg/dL within 2 h"*, *"Last logged meal 85 g carbs (high-carb), 25 min ago"*, *"Slept 4.6 h last
  night"* and *"HbA1c 9.1%"*, each tagged with its source (EHR or wearable).

### 2:20 – 3:10 | Live injection: watch the prediction react
* Select a **GREEN** patient. In the top bar click **Inject → Heavy carb meal**.
* Within one or two ticks the meal log reaches the twin, the risk jumps to **AMBER/RED**, an alert
  toast appears and the countdown shows ~30–60 min. Then the CGM rises.
* Speed up to **300x**. The alert card on the right updates its **track record** to *"spike occurred
  (lead NN min)"*. Alerts that turn out wrong are shown as *"no spike (false alert)"*.
* Optional: **Inject → CGM sensor dropout**. The data-quality indicator turns *degraded* and the
  header says "last value carried forward (imputed)". The twin keeps predicting with wider uncertainty.

### 3:10 – 4:10 | What-if simulator
* **"Walk 20 min now"**: the twin's personalised physiological model simulates baseline vs walking.
  Read the table: peak drop and minutes above 180.
* **"60 g dinner 19:00 vs 21:00"**: two scenarios overlaid. Show how the late dinner's peak lands
  near bedtime.
* **"Sleep 5 h vs 8 h"**: a short night lowers insulin sensitivity, so tomorrow's breakfast spike is higher.
* Point out the footnote: the twin is personalised (SI and Gb multipliers calibrated to this patient's
  CGM). *"It's a model estimate to support a conversation, not a treatment recommendation."*

### 4:10 – 4:40 | Clinician actions and audit
* **Acknowledge** the alert, **add a note**, and **suggest an intervention** ("post-dinner walk").
  The **audit trail** shows each action with a pseudonymous user and the simulated time.

### 4:40 – 5:00 | Results and honesty
* Footer: held-out test ROC-AUC / PR-AUC, mean lead time and false alerts per patient-day
  (from `reports/evaluation_report.md`).
* "Fusion helps most when the wearable history is short or degraded. In the steady state, 24 h of CGM
  already carries most of the signal. We report that honestly. Next steps are real Indian CGM data
  under ethics approval, federated learning and ABDM/FHIR integration."
