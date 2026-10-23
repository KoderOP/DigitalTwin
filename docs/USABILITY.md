# Usability evaluation kit (patient app)

> For 5–10 **non-clinician volunteers** using the synthetic demo. No real health data is collected. Do not ask
> volunteers for their own medical information. Record only task outcomes and SUS answers, under a volunteer code (V01…).

## 1. Session setup (facilitator)
1. `python tasks.py reset-portal` then `make demo`.
2. As the doctor, launch a patient interface (any template) in the volunteer's preferred language (EN / HI / TA).
3. Give the volunteer a phone or a narrow browser window (about 360–400 px). Read: *"This is a demo with made-up data. We
   are testing the app, not you. Please think aloud."*

## 2. Tasks (observe; do not help unless stuck for > 2 min)
| # | Task (read aloud) | Success criterion | Record |
|---|---|---|---|
| T1 | "Your doctor sent you this link. Start using the app." (hand over the invite link or QR) | Reaches Home after OTP, consent, language and tour | time, errors, help needed |
| T2 | "You just ate dal-chawal. Tell the app." | Meal logged with a portion | time-to-log (also measured in app), taps |
| T3 | (facilitator injects a heavy meal and steps 2 ticks) "Look at the app. What is it telling you, and what would you do?" | Explains: sugar may go high in about X min, suggests a walk; not alarmed | comprehension 0–2, in-app "Did this make sense?" answer |
| T4 | "Find out whether a 15-minute walk would help." | Uses Try it -> walk; reads the before/after sentence | time, correct reading of "estimate" |
| T5 | "Who has looked at your data? How would you stop sharing?" | Opens Me -> access log; finds Withdraw | success yes/no |

Comprehension scoring for T3: 2 = correct direction and timing and a sensible action; 1 = partially right;
0 = misunderstood or frightened.

## 3. System Usability Scale (SUS) template
Rate 1 (strongly disagree) to 5 (strongly agree). Hindi/Tamil translations of SUS should come from a validated version.
Do not use ad-hoc translations for scoring.

| # | Statement | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| 1 | I think that I would like to use this app frequently. | | | | | |
| 2 | I found the app unnecessarily complex. | | | | | |
| 3 | I thought the app was easy to use. | | | | | |
| 4 | I think that I would need the support of a technical person to be able to use this app. | | | | | |
| 5 | I found the various functions in this app were well integrated. | | | | | |
| 6 | I thought there was too much inconsistency in this app. | | | | | |
| 7 | I would imagine that most people would learn to use this app very quickly. | | | | | |
| 8 | I found the app very cumbersome to use. | | | | | |
| 9 | I felt very confident using the app. | | | | | |
| 10 | I needed to learn a lot of things before I could get going with this app. | | | | | |

**Scoring:** odd items contribute (score − 1), even items contribute (5 − score). Sum × 2.5 gives 0–100. The commonly
cited benchmark average is ~68.

Results sheet (one row per volunteer):
`volunteer, language, T1_s, T1_ok, T2_s, T3_comprehension, T4_ok, T5_ok, SUS, notes`

## 4. In-app metrics (computed by the backend, never hand-entered)
`GET /api/portal/metrics` (doctor token) returns:
* `median_time_to_log_meal_s`: from the first tap to saving a meal (client-measured, sent with each log).
* `alerts_per_patient_day`: delivered notifications per patient per simulated day (safety + capped heads-ups).
* `alert_comprehension`: share of "Did this make sense?" answers that were *yes*.

Per-patient values appear in the doctor's engagement panel. **No results are reported here until real sessions have
been run.**

## 5. Simulated behaviour-response check (not clinical evidence)
`python tasks.py behaviour` (or `make behaviour`) runs paired virtual-patient arms (no app / follows 50% / follows 100% of
suggestions) and writes [reports/behaviour_response.md](../reports/behaviour_response.md). It only shows that the
model -> suggestion -> behaviour -> physiology loop works **inside the simulator**.
