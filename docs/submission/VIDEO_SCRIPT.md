# Video recording script (target 22–26 minutes)

> The submission needs a video of at least 20 minutes, as an unlisted YouTube video or a narrated PowerPoint.
> This script combines a narrated deck (part A, about 18 min) and a live screen-recorded demo (part B, about 9–10 min).
> Every patient on screen is synthetic. Keep the "SYNTHETIC DATA ONLY" banner visible.

## Recording setup
* **Part A (deck):** open `docs/submission/Presentation.pptx` -> *Slide Show -> Record* (records narration per slide).
  The speaker notes on each slide are the narration (about 1 min each, 19 slides). Export with *File -> Export -> Create a Video*
  (1080p), or record the screen with OBS.
* **Part B (live demo):** before recording, run `python tasks.py reset-portal` then `make demo` (or `python tasks.py demo`).
  Wait for "Engine ready", then open http://127.0.0.1:8000 in a browser window about 1400 px wide, and a second **private** window
  about 400 px wide (or a phone on the same Wi-Fi, see docs/DEMO_PATIENT.md) for the patient app. Record with OBS
  (two window sources side by side) at 1080p.
* Upload to YouTube as **Unlisted**, then paste the link into README.md (section *Demo video*).

## Part A: narrated deck (about 15 min)
| Time | Slide | Key message (full narration in the speaker notes) |
|---|---|---|
| 0:00 | 1 Title | Team, the one-sentence idea, the synthetic-data notice |
| 1:00 | 2 Problem | ~101 M people with diabetes in India; HbA1c hides daily spikes |
| 2:00 | 3 Use case | Four outputs every 5 min: risk, forecast, level + countdown, why/what-if |
| 3:00 | 4 Solution | Two streams -> fusion -> twin -> two role-based apps |
| 4:00 | 5 Synthetic data | EHR generator + physiological simulator; GMI vs HbA1c r = 0.95 |
| 5:15 | 6 Models | LightGBM baseline vs GRU + EHR cross-attention + gated fusion |
| 6:30 | 7 Evaluation | Patient split, temporal, cold start, live replay, fairness, robustness |
| 7:30 | 8 Results | ROC-AUC 0.938; 80% of spikes caught ~45 min ahead at ~1 false alert/day |
| 8:45 | 9 Fusion ablation | No steady-state gain; +0.02 at cold start; 80% vs 75% at RED |
| 10:00 | 10 Forecast | Beats "no change" at all horizons; band slightly over-confident |
| 10:45 | 11 Twin / what-if | Personalised simulator; walk, roti, dinner time, sleep |
| 11:45 | 12 Doctor dashboard | Live triage, explanation, injections, audit |
| 12:30 | 13 Patient app | Doctor-launched, consent-first, 3 languages |
| 13:30 | 14 Food-impact AI | 14-day food diary; flags foods worse than *this* patient's usual meal; symptom links; gentle warnings; 3 demo accounts |
| 14:45 | 15 Safety & privacy | Always-on safety alerts, consent gate, RBAC, audit |
| 15:30 | 16 Behaviour sim | Time > 180: 20.6% -> 13.0% -> 10.5% (simulated only) |
| 16:15 | 17 Tech stack | Stack, one-command demo, 63 + 16 tests |
| 16:45 | 18 Limitations | Synthetic data, not a device; path: study -> federated -> ABDM -> trial |
| 17:30 | 19 Thank you | Summary, repo link, MIT license; "now the live demo" |

## Part B: live demo (about 9–10 min), screen recording
| Time | Scene | What to do and say |
|---|---|---|
| 16:45 | B1 Dashboard tour (90 s) | Point at the banner and sim clock (60x). Cohort sorted by risk with icon + text badges and the patient-app status column. Open the top patient: header, live CGM + forecast band, risk gauge + countdown, wearable panels, "Why this alert?", metrics + AGP |
| 18:15 | B2 Early warning (60 s) | Open a patient whose risk strip shows an earlier AMBER/RED episode. "Risk crossed RED here, well before the glucose rose." Show the alert card's track record ("spike occurred, lead NN min") |
| 19:15 | B3 Launch the patient app (90 s) | Pick a *Not enrolled* patient -> **Launch patient interface** -> template -> language **हिन्दी** -> show the locked safety alerts -> **Save & preview as patient** (phone frame) -> **Launch** -> QR code, expiry countdown, Resend / Regenerate |
| 20:45 | B4 Patient activation (90 s) | Open the invite in the second window: welcome -> OTP (read it from the Dev outbox toast or "Demo: show my code") -> consent screen (read purpose and rights aloud) -> language -> tour -> Connect (simulated) -> Start. Doctor panel now shows **Active** |
| 22:15 | B5 Live event (75 s) | Doctor: **Inject -> Heavy carb meal**, press **+5 min** twice. Doctor gauge goes RED with a countdown; patient Home shows the plain-language sentence, confidence, next action and "why"; Care tab shows the alert with "not medical advice" |
| 23:30 | B6 Patient responds (75 s) | Patient: **Try it -> "What if I walk 15 minutes now?"** (before/after) -> **Log -> 15 min walk**. Doctor: engagement panel updates (logs, time-to-log). Doctor pushes a care-plan card and a message; patient marks it **Done** |
| 24:45 | B7 Food patterns (75 s) | Patient: **My Day -> My food patterns** (foods to watch, rice-vs-roti pattern, 7-day diary). **Log -> Biryani (Large)** and **Thirsty**, step the clock: the "About biryani…" warning appears and the symptom is linked to the food. Doctor: **Food and symptom insights** table and diary |
| 26:00 | B8 Demo accounts (30 s) | Open `/patient/` in a fresh window: three ready demo accounts (English / हिन्दी / தமிழ்); tap the Tamil one to show the localised app |
| 26:30 | B9 Control and privacy (60 s) | Doctor **Pause** -> patient app shows "paused". **Resume**. Patient **Me -> Who viewed my data**. Doctor **Revoke** -> patient app disconnects. Show the audit trail |
| 27:30 | Close (15 s) | "Synthetic data only, not a medical device. Code and report are in the repository. Thank you." |

## Checklist before upload
- [ ] Total length ≥ 20 min (target about 27 min)  - [ ] Synthetic-data notice visible in both parts
- [ ] No personal information on screen (browser profile, bookmarks, notifications hidden)
- [ ] YouTube visibility **Unlisted**; link added to README.md
