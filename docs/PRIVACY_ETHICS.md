# Privacy, compliance and ethics note

> **SYNTHETIC DATA ONLY: NOT FOR CLINICAL USE.** This is a research prototype. It is not a medical
> device, it has no regulatory clearance, and it has no clinical validation.

## 1. Data used

* **No real patient data.** All EHR records and all wearable/CGM signals are produced by our generators
  (`data_gen/`). Optional adapters (Synthea, open CGM datasets, MIMIC-IV) are **off by default** and
  documented only. The project never downloads data.
* Patient IDs are random pseudonyms (`TWN-xxxxxx`). There are no names, addresses, phone numbers, Aadhaar
  or ABHA numbers, dates of birth or free-text identifiers anywhere.

## 2. How the PoC shows DPDP Act 2023 / HIPAA-style safeguards

| Principle | Implementation in the PoC |
|---|---|
| **Lawful purpose and consent** (DPDP s.4-6) | Each twin has a *simulated* consent record (`consent` table, scope `twin_monitoring+clinician_view`). The API returns **403** for a patient whose consent is withdrawn (tested in `tests/test_api.py`) |
| **Data minimisation** (DPDP s.6(1); HIPAA minimum necessary) | Ingestion keeps only device fields (`DEVICE_FIELDS`). Simulator ground truth (`glucose_true`, adherence, habits) is never served. The dashboard shows only the EHR items needed for the alert decision |
| **Purpose limitation** | Data is used for one purpose: hyperglycemia risk monitoring. There are no secondary uses or exports |
| **Accountability / audit** (HIPAA §164.312(b)) | An append-only SQLite audit trail records every patient view, alert, acknowledgement, note, intervention suggestion, what-if run and demo control, with wall-clock time, simulated time and a pseudonymous actor ID. The dashboard shows it |
| **Storage limitation** | Twin buffers are bounded (~50 h of 5-min data, 14 days of CGM for the AGP). Nothing is retained beyond what the views need |
| **Security** (PoC level) | The server binds to `127.0.0.1` by default. There is **no authentication** in the PoC; a deployment would need SSO/RBAC, TLS, encryption at rest and key management |
| **Rights of the data principal** | Not implemented (no real principals). A deployment would need access, correction, erasure and grievance flows (DPDP s.11-13) |

## 3. Ethics and safety

* **Not a medical device.** The alert and the what-if trajectories are estimates. The what-if engine
  always labels its output "not a treatment recommendation". Insulin dosing is deliberately not offered.
* **Synthetic-data bias.** The models learn the simulator's assumptions (`docs/ASSUMPTIONS.md`).
  Any population stereotype written into the generator (diet by region, activity by urban/rural) can
  be reproduced by the model. We report subgroup performance (age, sex, BMI band, urban/rural), but with
  ~23 test patients those estimates are noisy.
* **Alert fatigue.** False alerts per patient-day are measured and reported. Thresholds are chosen on
  validation data, not tuned on test data.
* **Automation bias.** The dashboard shows uncertainty bands, the evidence ("Why this alert?"), each
  alert's track record (spike occurred / no spike), and a data-quality indicator when the stream is
  being imputed.
* **Equity.** CGMs and smartwatches are costly in India. A real programme must check performance on
  lower-cost sensor setups (e.g. intermittent fingersticks + phone pedometer) and in rural settings.

## 4. Path to real-world validation

1. **Retrospective validation** on consented Indian CGM + EHR data under an ethics-committee-approved
   protocol (ICMR National Ethical Guidelines), with a data-processing agreement and DPDP-compliant
   consent artefacts.
2. **Federated learning** across hospitals and incubator partners (e.g. Flower or NVIDIA FLARE): models
   train where the data lives, and only weights or gradients (with secure aggregation and,
   optionally, differential privacy) leave the site.
3. **Interoperability via ABDM / FHIR.** EHR ingestion through ABDM's Health Information Exchange using
   FHIR R4 profiles. The PoC already exports FHIR (`data/ehr/fhir_bundle.json`). Consent goes through
   ABDM consent-manager artefacts and patient linking through ABHA.
4. **Prospective silent trial.** Run alerts in the background without showing them to clinicians,
   and compare with outcomes.
5. **Regulatory.** CDSCO classification under the Medical Devices Rules 2017 (software as a medical
   device), with a clinical performance study, a risk-management file (ISO 14971) and software lifecycle
   documentation (IEC 62304).
