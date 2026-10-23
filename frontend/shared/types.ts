/** Types shared by the doctor dashboard and the patient app. */
export type Level = "GREEN" | "AMBER" | "RED" | "HIGH";
export type PatientLevel = Level | "LOW";
export type Trend = "up_fast" | "up" | "flat" | "down" | "down_fast";
export type PortalState = "NOT_ENROLLED" | "INVITED" | "CONSENT_PENDING" | "ACTIVE" | "PAUSED" | "REVOKED";
