# PATIENT_PLAN: doctor-initiated patient interface

> SYNTHETIC DATA ONLY: NOT FOR CLINICAL USE.

## Concept
The patient app exists only because a doctor launched it for that patient. The **twin is the single
source of truth**. The doctor dashboard and the patient PWA are two role-based clients of the same twin
objects and the same engine tick.

## Reused (not rebuilt)
| Existing piece | Reuse |
|---|---|
| `backend/engine.py` `Engine` (world -> twins -> predictions, injections) | Patient channel is fed from the same tick. Quick Log and Try-It call the same twin / world |
| `twin/twin.py` `DigitalTwin` (prediction, explanation factors, alerts, what-if) | Patient view is a minimised, translated projection of `twin.prediction` / `twin.detail()` |
| `twin/whatif.py` | Patient "Try it" presets are scenario lists for `run_what_if` |
| `ml/explain.py` factors | Plain-language, localised sentences (backend explanation service) |
| `backend/audit.py` SQLite | Extended with portal tables (state, config, invites, sessions, messages, cards, logs, notifications) |
| Doctor dashboard components (`LevelBadge`, `Card`, format helpers, colour palette) | Moved to `frontend/shared` and used by both apps |

## Key decisions (defaults; documented in docs/PATIENT_INTERFACE.md)
| Topic | Decision |
|---|---|
| Lifecycle | `NOT_ENROLLED -> INVITED -> CONSENT_PENDING -> ACTIVE <-> PAUSED`, any non-terminal -> `REVOKED`, `REVOKED -> INVITED` (re-launch). Invalid transitions return 409. Every transition is audited |
| Enroll / configure | Happen in `NOT_ENROLLED` (twin exists, configuration saved). Launch requires a valid configuration |
| Auth | PyJWT HS256. Roles: `doctor`, `patient`, `caregiver`, `preview` (doctor's read-only "view as patient"). Secret from `DT_JWT_SECRET` or a generated file in `data/` |
| Doctors | Two fictional demo doctors in config, each assigned half of the demo patients. Doctors can only provision their own patients |
| Invite | Signed JWT (typ=invite, jti) plus a server-side record, so it is single-use and regenerate/revoke invalidates the old one. 48 h expiry (config). Link `/patient/?invite=...` + QR |
| OTP | 6 digits, hashed, 5-min expiry, max 5 attempts (then the invite is locked), per-IP rate limit. **Mock delivery** to a dev outbox shown in the doctor dashboard and a demo-only "show my code" helper |
| Device binding | Client-generated device id. Its hash is bound at OTP verification and checked on every patient request |
| Consent gate | Patient endpoints return **no twin data unless state = ACTIVE and the session is current**. Withdraw -> REVOKED, session killed, WebSocket closed, patient logs rejected |
| Two-way channel | `/ws/patient` pushes state, forecast, alerts, cards and messages each tick. Patient logs / acks / symptoms go over REST to the twin and the doctor's engagement panel |
| Quick Log in the simulator | A log both **performs** the action in the virtual patient's world (meal eaten, walk taken, dose taken/missed) and records it, so the next prediction reflects it. Documented assumption |
| Safety | RED and hypo (< 70 predicted or detected) alerts are hard-wired on and bypass frequency caps (deduplicated per episode only). The configuration schema cannot disable them. First-aid text. No medication changes, ever |
| Notifications | Non-safety alerts: daily cap + minimum gap (doctor-configurable within bounds). Priority: safety > doctor message > care-plan > info |
| i18n | English, Hindi, Tamil (react-i18next on the frontend; YAML content files on the backend). **Translations are machine-drafted and need native-speaker review** |
| Frontend layout | `frontend/doctor` (migrated dashboard), `frontend/patient` (PWA), `frontend/shared`. One Vite multi-page build, both served by FastAPI on one port (`/` and `/patient/`) |

## Phases
- [x] **A** Provisioning backend: state machine, config store + bounds, invites, OTP, consent, sessions, RBAC/JWT, audit, notification service, explanation service, patient view, patient WebSocket
- [x] **B** Doctor side: Patient Interface Manager, launch wizard with templates, QR / expiry / resend / regenerate, preview, engagement, messages, status column + bulk invite, dev outbox
- [x] **C** Patient PWA core: onboarding (invite -> OTP -> consent -> language -> tour -> wearable), Home, My Day, Alerts
- [x] **D** Quick Log, Try-It, Progress, care-plan cards, messages (two-way)
- [x] **E** i18n (en/hi/ta), accessibility (360 px, screen reader, voice prompts), safety guardrails, PWA (manifest + service worker)
- [x] **F** Tests (pytest + vitest + end-to-end), docs/DEMO_PATIENT.md, usability script + SUS, in-app metrics, simulated behaviour-response study

## Added on request (after Phase F)
- [x] **Daily consumption pattern + personal food-impact AI**: 14-day food diary, per-food CGM response, foods flagged when consistently high *and* worse than the patient's usual meal, late-dinner / rice-vs-roti patterns, symptom-to-food links, gentle warnings on re-logging (patient My Day + doctor card). Tests: tests/test_food_insights.py
- [x] **3 demo patient accounts** (English / Hindi / Tamil), pre-activated through the audited lifecycle, one-tap login on /patient/ (demo-only flag). Tests: tests/test_zz_demo_accounts.py
