import type { Level } from "@shared/types";
export type { Level };

export interface Summary {
  patient_id: string;
  age: number;
  sex: string;
  region: string;
  hba1c: number;
  bmi_band_sa: string;
  insulin: boolean;
  cgm: number | null;
  g_now: number | null;
  trend: "up_fast" | "up" | "flat" | "down" | "down_fast";
  risk: number | null;
  level: Level;
  minutes_to_spike: number | null;
  nocturnal_flag: string | null;
  hypo_risk: number | null;
  active_alerts: number;
  data_quality: "good" | "degraded" | "poor";
  ts: string | null;
}

export interface SimState {
  clock: string;
  speed: number;
  paused: boolean;
  speeds: number[];
  mode: string;
  patients: number;
  tick_ms: number;
  injections: { event: string; label: string }[];
}

export interface ForecastPoint { minutes: number; p10: number; p50: number; p90: number }

export interface Factor {
  factor: string;
  title: string;
  source: string;
  contribution: number;
  share: number;
  direction: "increases" | "decreases";
  text: string;
}

export interface Prediction {
  model: string;
  risk: number;
  level: Level;
  eligible: boolean;
  g_now: number;
  hypo_risk: number | null;
  forecast: ForecastPoint[];
  minutes_to_spike: number | null;
  minutes_to_spike_basis: string | null;
  thresholds: { amber: number; red: number };
  explanation?: Factor[];
  nocturnal_flag: string | null;
  ts: string;
}

export interface SeriesPoint {
  ts: string;
  cgm: number | null;
  hr: number | null;
  hrv_rmssd: number | null;
  steps: number | null;
  activity: number | null;
  sleep_stage: number | null;
  spo2: number | null;
}

export interface EventItem { ts: string; type: string; name: string; label: string; amount: number | null; injected: boolean }

export interface Alert {
  id: number;
  patient_id?: string;
  ts: string;
  level: Level;
  risk: number;
  minutes_to_spike: number | null;
  status: "active" | "acknowledged";
  outcome: "pending" | "spike_occurred" | "no_spike";
  lead_min?: number;
  acknowledged_by?: string;
  g_at_alert: number;
  top_factors: string[];
}

export interface Metrics { mean: number; sd: number; cv: number; gmi: number; tir: number; tar: number; tar250: number; tbr: number; tbr54: number; coverage: number }

export interface Detail {
  header: {
    patient_id: string; age: number; sex: string; region: string; years_since_dx: number; hba1c: number; bmi: number;
    bmi_band_sa: string; waist_cm: number; egfr: number; diet: string; staple: string; early_onset: boolean; prs: number;
    medications: string[]; comorbidities: string[]; fasting_glucose: number; ldl: number; triglycerides: number;
  };
  summary: Summary;
  series: SeriesPoint[];
  events: EventItem[];
  prediction: Prediction | null;
  prediction_history: { ts: string; risk: number | null; level: Level; p50_60: number; p10_60: number; p90_60: number }[];
  metrics_24h: Metrics;
  metrics_14d: Metrics;
  agp: { minute: number; p5: number; p25: number; p50: number; p75: number; p95: number }[];
  daily: { date: string; tir: number; tar: number; tbr: number; mean: number; cv: number }[];
  data_quality: { cgm_coverage_1h: number; cgm_coverage_24h: number; wearable_coverage_1h: number; minutes_since_cgm: number | null; status: string; imputing: boolean };
  alerts: Alert[];
  notes: { ts: string; user: string; text: string }[];
  simulator: { si_mult: number; gb_mult: number; Gb: number; calibration_rmse: number | null; n_calibrations: number };
  last_sleep_h: number | null;
  consent: { status: string; scope: string; note: string } | null;
}

export interface Intervention {
  type: "meal" | "exercise" | "medication" | "sleep";
  carbs?: number; gi?: "low" | "medium" | "high"; minutes?: number; intensity?: "light" | "moderate" | "vigorous";
  drug?: "metformin" | "sulfonylurea" | "rapid_insulin" | "basal_insulin"; dose?: number; hours?: number; at?: string; in_min?: number;
}
export interface ScenarioReq { name: string; interventions: Intervention[] }

export interface WhatIfResult {
  start: string;
  horizon_min: number;
  times: string[];
  baseline: { name: string; trajectory: number[]; summary: Record<string, number> };
  scenarios: { name: string; interventions: Intervention[]; trajectory: number[]; summary: Record<string, number> }[];
  notes: string[];
  simulator: Detail["simulator"];
}

export interface Meta {
  banner: string;
  model: string;
  thresholds: { amber: number; red: number };
  headline_test_metrics: { roc_auc?: number; pr_auc?: number; mean_lead_min?: number; false_alerts_per_patient_day?: number; event_sensitivity?: number; notify_level?: string };
  provenance: Record<string, string | number | null>;
  compliance: string[];
}

export interface AuditRow { id: number; ts_wall: string; ts_sim: string | null; actor: string; action: string; patient_id: string | null; detail: Record<string, unknown> }
