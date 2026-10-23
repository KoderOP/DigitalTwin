# Demo script: doctor-initiated patient app (about 6 minutes)

> SYNTHETIC DATA ONLY: NOT FOR CLINICAL USE. Every patient, phone number and doctor here is fictional.

## Before you start
```bash
python tasks.py reset-portal   # optional: fresh invites/consents (or: make reset-portal)
make demo                      # or: python tasks.py demo
```
* Doctor dashboard: http://127.0.0.1:8000/ (signed in as the fictional **Dr. Asha Mehta**; switch doctors in the top-right selector).
* Patient app: opened from the invite link or QR code. For a demo on one laptop, use a **second browser window**
  (ideally a private window, so it gets its own device id).
* Real phone: on the same Wi-Fi, start the server with `DT_HOST=0.0.0.0` and
  `DT__PORTAL__PUBLIC_BASE_URL=http://<laptop-LAN-IP>:8000`, then scan the QR code.
* Keep the speed at **60x** (a 5-min tick every 5 s). Use **+5 min** to step manually while talking.

**Shortcut: 3 ready-made demo patient accounts.** Open http://127.0.0.1:8000/patient/ (no invite) and tap
*Demo patient 1 (English) / 2 (हिन्दी, on insulin) / 3 (தமிழ், older adult + caregiver)*. They are already ACTIVE
(seeded through the audited lifecycle), which is handy when there's no time for the invite flow. The full flow below is
still the main story.

## 1. Pick a "Not enrolled" patient (doctor)
In the cohort list each row has a status chip (**Not enrolled / Invited / Active / Paused / Revoked**). Rows marked
*other doctor* belong to Dr. Rao: Dr. Mehta cannot launch an app for them (role-based access). Pick one of
Dr. Mehta's **Not enrolled** patients. *(Optional: tick several and use **Bulk invite**, or **+ New synthetic patient**.)*

## 2. Launch the patient interface (doctor, under 2 minutes)
In the **Patient Interface Manager** card click **Launch patient interface**:
1. *Template*: e.g. "Standard T2D follow-up". Medication reminders are pre-filled from the EHR prescription.
2. *Language & targets*: pick **हिन्दी** or **தமிழ்**. The target range defaults to 70–180, and out-of-bounds values are refused.
   Note the lock icon: **RED and low-glucose alerts are always on.**
3. *Features & care plan*: Quick Log, Try-It, Progress, caregiver; diet guidance; step goal.
4. *Alerts & contacts*: daily cap, minimum gap, escalation contact (fictional).
5. **Save & preview as patient**: the right-hand phone frame shows *exactly* what the patient will see.
   Click **Launch & create secure invite**.

## 3. Invite -> OTP -> consent (patient)
The panel now shows a **QR code**, an **expiry countdown**, and **Resend / Regenerate** (regenerating instantly
invalidates the old link). Scan the QR code or click *Open patient link (2nd window)*.
* Welcome screen in the doctor's chosen language -> **Next**.
* OTP: the mock SMS appears in the doctor's **Dev outbox** (bottom-left) and as a toast. On the patient side,
  *Demo: show my code* reveals it. Enter it. (Five wrong codes lock the invite. Invites are single-use.)
* **Consent**: purpose, data used, who sees it, rights, and the synthetic-data notice. Choose whether logs are shared with
  the doctor -> language -> 3-step tour -> **Connect (simulated)** wearable -> **Start**.
* Only now does the state become **ACTIVE**, and the live twin streams to the phone (doctor panel: *Active*).

## 4. Inject a heavy-carb meal (doctor)
With the patient selected, click **Inject -> Heavy carb meal** in the demo bar. Step +5 min once or twice.

## 5. The spike prediction on both screens
* Doctor: the risk gauge goes to **RED** with a countdown, and the alert toast and CGM forecast band rise.
* Patient: the Home status changes to an icon + word + plain sentence, e.g. *"Your sugar is likely to go high in about
  40 minutes."* It shows a confidence label, the next action (*"Take a 15-minute walk now"*) and *Why is this happening?* in
  everyday language. The **Care** tab shows the alert card with its confidence, the "not medical advice" notice and a
  *"Did this make sense?"* check.

## 6. The patient responds (two-way channel)
* Patient: **Try it -> "What if I walk 15 minutes now?"** shows a before/after estimate.
* Patient: **Log -> 15 min walk** (one tap). The walk is performed in the virtual patient's world, the steps reach
  the twin, and over the next ticks the glucose trend and forecast respond.
* Doctor: the **engagement panel** updates (*Logs completed*, *Median time to log*, *Recent patient logs*).
  Send a message or **push a care-plan card**. It appears on the phone's Care tab, where the patient can **Mark done**.

## 6b. Food patterns: which foods push *this* patient's sugar up
* Patient: **My Day -> My food patterns** shows *Foods to watch* (e.g. biryani: "rose about 100 mg/dL, above 180 after
  100% of these meals, based on 5 meals"), patterns (late dinners, rice vs roti), the 7-day food diary and symptom links.
* Patient: **Log -> Biryani (Large)**, then **Thirsty**. Step the clock. A gentle *"About biryani…"* warning appears in Care,
  and the symptom is linked to the food (with the glucose at that time).
* Doctor: the **Food and symptom insights** card shows the per-food table (n, mean rise/peak, % above, vs usual, evidence)
  and the day-by-day diary.

## 7. Pause / revoke and the audit trail
* Doctor clicks **Pause**: the phone immediately shows "Your care team has paused the app". **Resume** brings it back.
* Doctor clicks **Revoke** (or the patient taps **Me -> Withdraw consent**): the WebSocket is closed, the session is
  invalidated, logs are rejected, and the app shows that it is no longer active.
* Show the audit trail: doctor dashboard -> *Clinician actions -> Audit trail*, and on the phone *Me -> Who viewed my data*.
  Every invite, OTP, consent, configuration edit, state change, view, log and message is listed.

## Safety talking points
* RED and low-glucose alerts cannot be disabled by doctor or patient (the schema rejects it) and bypass frequency caps.
* Low-glucose cards show first aid (15 g fast sugar, re-check in 15 min) and a **tap-to-call 108** button.
* The app never changes medication. Reminders refer to the existing prescription, and questions are routed to the doctor.
