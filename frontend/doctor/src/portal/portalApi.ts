import type { PortalState } from "@shared/types";

export interface Doctor { id: string; name: string; title: string }
export interface PortalStatus { patient_id: string; state: PortalState; doctor_id: string; assigned_to_me: boolean; configured: boolean; last_activity: string | null }
export interface Invite { status: string; expires_at: string; seconds_left: number; sends: number; attempts: number; link: string | null }
export interface Engagement {
  alerts_delivered: number; alerts_seen: number; safety_alerts: number; alerts_suppressed_by_cap: number; escalations: number;
  alert_comprehension: number | null; alerts_per_day: number | null; logs: Record<string, number>; median_time_to_log_s: number | null;
  recent_logs: { ts_sim: string; kind: string; payload: Record<string, unknown> }[];
  messages_sent: number; messages_read: number; cards_total: number; cards_done: number;
}
export interface PortalConfig {
  template: string; language: "en" | "hi" | "ta";
  target: { low: number; high: number };
  alerts: { amber_threshold: number; daily_cap: number; min_gap_min: number; escalate_after_min: number;
    escalation_contacts: { name: string; relation: string; channel: "sms" | "email"; handle: string }[]; red_alerts: true; low_glucose_alerts: true };
  features: { quick_log: boolean; try_it: boolean; progress: boolean; caregiver: boolean };
  care_plan: { diet: string[]; steps_goal: number; post_meal_walk: boolean; walk_minutes: number; medication_reminders: { label: string; time: string }[] };
}
export interface Manager {
  patient_id: string; state: PortalState; doctor: Doctor; assigned_to_me: boolean; config: PortalConfig | null;
  consent: { version: string; accepted_at: string; choices: Record<string, boolean>; withdrawn_at?: string } | null;
  last_activity: string | null; invite: Invite | null; engagement: Engagement;
  outbox: { id: number; ts: string; channel: string; recipient: string; body: string }[];
}

const KEY = "dt_doctor_token";
let token: string | null = (() => { try { return localStorage.getItem(KEY); } catch { return null; } })();

export class PortalError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
  if (!r.ok) {
    let detail: unknown = r.statusText;
    try { detail = (await r.json()).detail; } catch { /* not json */ }
    const msg = Array.isArray(detail) ? detail.map((d: { loc?: string[]; msg?: string }) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg}`).join("; ") : String(detail);
    throw new PortalError(r.status, msg);
  }
  return r.json() as Promise<T>;
}
const post = <T,>(p: string, body: unknown = {}) => req<T>(p, { method: "POST", body: JSON.stringify(body) });

export const portal = {
  hasToken: () => !!token,
  async login(doctor_id: string, password = "demo"): Promise<Doctor> {
    const r = await post<{ token: string; doctor: Doctor }>("/api/auth/login", { doctor_id, password });
    token = r.token;
    try { localStorage.setItem(KEY, r.token); localStorage.setItem("dt_doctor_id", doctor_id); } catch { /* blocked */ }
    return r.doctor;
  },
  doctors: () => req<Doctor[]>("/api/portal/doctors"),
  templates: () => req<Record<string, { label: string }>>("/api/portal/templates"),
  status: () => req<PortalStatus[]>("/api/portal/status"),
  manager: (pid: string) => req<Manager>(`/api/portal/patients/${pid}`),
  enroll: (pid: string, template: string) => post<Manager>(`/api/portal/patients/${pid}/enroll`, { template }),
  newPatient: (template: string) => post<Manager>("/api/portal/patients/new", { template }),
  templateConfig: (pid: string, template: string) => post<PortalConfig>(`/api/portal/patients/${pid}/template-config`, { template }),
  saveConfig: (pid: string, cfg: PortalConfig) => req<Manager>(`/api/portal/patients/${pid}/config`, { method: "PUT", body: JSON.stringify(cfg) }),
  launch: (pid: string) => post<Invite>(`/api/portal/patients/${pid}/launch`),
  regenerate: (pid: string) => post<Invite>(`/api/portal/patients/${pid}/regenerate`),
  resend: (pid: string) => post<Invite>(`/api/portal/patients/${pid}/resend`),
  pause: (pid: string) => post<Manager>(`/api/portal/patients/${pid}/pause`),
  resume: (pid: string) => post<Manager>(`/api/portal/patients/${pid}/resume`),
  revoke: (pid: string) => post<Manager>(`/api/portal/patients/${pid}/revoke`),
  previewToken: (pid: string) => post<{ token: string; path: string }>(`/api/portal/patients/${pid}/preview-token`),
  message: (pid: string, body: string) => post(`/api/portal/patients/${pid}/messages`, { body }),
  card: (pid: string, title: string, body: string) => post(`/api/portal/patients/${pid}/cards`, { title, body, kind: "intervention" }),
  bulkInvite: (patient_ids: string[], template: string) => post<{ patient_id: string; ok: boolean; link?: string; error?: string }[]>("/api/portal/bulk-invite", { patient_ids, template }),
  outbox: () => req<{ id: number; ts: string; pid: string; channel: string; recipient: string; body: string }[]>("/api/portal/outbox"),
};
