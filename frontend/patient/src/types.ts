import type { PatientAlert } from "@shared/components/AlertCard";
import type { PatientLevel, PortalState, Trend } from "@shared/types";

export interface Doctor { id: string; name: string; title: string }
export interface Features { quick_log: boolean; try_it: boolean; progress: boolean; caregiver: boolean }

export interface PatientView {
  state: PortalState | string;
  language: string;
  now: string;
  patient_id: string;
  doctor: Doctor;
  features: Features;
  target: { low: number; high: number };
  status: { level: PatientLevel; icon: string; sentence: string; sub: string | null; minutes_to_spike: number | null;
    confidence: { pct: number | null; label: string; key: string } };
  glucose: { value: number | null; estimated: number | null; trend: Trend; trend_icon: string; trend_text: string; unit: string; ts: string | null;
    history: { ts: string; g: number | null }[]; forecast: { minutes: number; low: number; mid: number; high: number }[]; sensor_ok: boolean; imputing: boolean };
  next_action: { key: string; icon: string; text: string; safety?: boolean };
  why: { sentence: string; items: { text: string; direction: "up" | "down" }[] };
  safety: { low_now: boolean; first_aid: PatientAlert["first_aid"]; note: string };
  my_day: { ts: string; kind: string; icon: string; text: string }[];
  progress: { today_tir: number; week_tir: number; message: string; week_text: string; streak: number; streak_text: string | null;
    days: { date: string; tir: number; mean: number }[]; good_days: number } | null;
  alerts: PatientAlert[];
  cards: { id: number; ts_sim: string; source: string; kind: string; title: string; body: string; status: string }[];
  messages: { id: number; ts_sim: string; sender: string; author: string; body: string; read_at: string | null }[];
  care_plan: { items: { kind: string; text: string }[]; med_note: string };
  disclaimer: string;
  food?: FoodInsights;
}

export interface FoodInsights {
  foods: { key: string; label: string; n: number; mean_rise: number; mean_peak: number; pct_above: number; mean_carbs: number;
    minutes_above: number; relative_to_usual: number | null; flag: "watch" | "ok"; confidence: "high" | "medium" | "low"; text: string; based_on: string }[];
  patterns: { key: string; text: string; n: number }[];
  symptom_links: { food: string; label: string; symptom: string; n: number; glucose_at_symptom: number | null; pattern: boolean; text: string }[];
  diary: { date: string; total_carbs: number; meals: number; late_meals: number; sweets: number; spikes_after_meals: number;
    items: { time: string; key: string; label: string; carbs: number; peak: number | null; went_above: boolean | null; watch: boolean }[] }[];
  usual_rise: number | null; meals_analysed: number; meals_logged: number; high: number; tip: string; method: string;
}

export interface PendingView { state: "CONSENT_PENDING"; language: string; doctor: Doctor; consent_version: string; features: Features; caregiver_allowed: boolean }
export interface PausedView { state: "PAUSED"; language: string; doctor: Doctor; message: string }
export interface CaregiverView { state: "CAREGIVER"; language: string; doctor: Doctor; status: PatientView["status"];
  glucose: Pick<PatientView["glucose"], "value" | "trend" | "trend_icon" | "trend_text" | "unit" | "ts">; alerts: PatientAlert[]; disclaimer: string }
export type AnyView = PatientView | PendingView | PausedView | CaregiverView;

export interface TryResult { preset: string; question: string; times: string[]; before: number[]; after: number[]; delta_peak: number; result: string; note: string;
  target: { low: number; high: number } }
