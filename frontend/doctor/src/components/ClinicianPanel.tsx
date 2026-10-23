import { useEffect, useState } from "react";
import { Check, ClipboardList, Send } from "lucide-react";
import { api } from "../api";
import type { AuditRow, Detail } from "../types";
import { LevelBadge } from "@shared/components/LevelBadge";
import { fmtDateTime, fmtTime, pct } from "@shared/lib/format";

const KINDS = [
  ["diet_advice", "Diet advice (carb portion / GI swap)"],
  ["activity_advice", "Post-meal walk / activity"],
  ["medication_review", "Medication review"],
  ["teleconsult", "Teleconsultation"],
  ["sensor_check", "Check CGM sensor"],
  ["other", "Other"],
] as const;

const OUTCOME: Record<string, string> = { pending: "outcome pending", spike_occurred: "spike occurred", no_spike: "no spike (false alert)" };

export function ClinicianPanel({ d, onChanged }: { d: Detail; onChanged: () => void }) {
  const pid = d.header.patient_id;
  const [note, setNote] = useState("");
  const [kind, setKind] = useState<string>("activity_advice");
  const [detail, setDetail] = useState("");
  const [audit, setAudit] = useState<AuditRow[]>([]);
  const refreshAudit = () => api.audit(pid).then(setAudit).catch(() => undefined);
  useEffect(() => { refreshAudit(); }, [pid, d.alerts.length, d.notes.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (fn: () => Promise<unknown>) => { await fn(); onChanged(); refreshAudit(); };
  const field = "w-full rounded border border-slate-300 bg-white px-2 py-1 text-xs dark:border-slate-700 dark:bg-slate-800";

  return (
    <div className="grid gap-4 md:grid-cols-3">
      <div>
        <h3 className="mb-2 text-xs font-semibold text-slate-700 dark:text-slate-200">Alerts ({d.alerts.length})</h3>
        <ul className="max-h-64 space-y-2 overflow-y-auto pr-1">
          {d.alerts.length === 0 && <li className="text-xs text-slate-500">No alerts yet.</li>}
          {d.alerts.map((a) => (
            <li key={a.id} className="rounded-lg border border-slate-200 p-2 text-xs dark:border-slate-700">
              <div className="flex items-center justify-between">
                <LevelBadge level={a.level} />
                <span className="font-mono text-slate-500">{fmtTime(a.ts)}</span>
              </div>
              <p className="mt-1 text-slate-700 dark:text-slate-300">
                Risk {pct(a.risk)} at {Math.round(a.g_at_alert)} mg/dL{a.minutes_to_spike != null && `, spike forecast in ~${a.minutes_to_spike} min`}.
              </p>
              {a.top_factors.length > 0 && <p className="text-[11px] text-slate-500">Drivers: {a.top_factors.join(", ")}</p>}
              <p className="text-[11px] text-slate-500">
                Track record: <span className="font-medium">{OUTCOME[a.outcome]}</span>
                {a.lead_min != null && ` (lead ${a.lead_min} min)`}
              </p>
              {a.status === "active" ? (
                <button onClick={() => act(() => api.ack(pid, a.id))} className="mt-1 flex items-center gap-1 rounded bg-brand px-2 py-0.5 text-white">
                  <Check className="h-3 w-3" aria-hidden /> Acknowledge
                </button>
              ) : (
                <p className="mt-1 text-[11px] text-slate-500">Acknowledged by {a.acknowledged_by}</p>
              )}
            </li>
          ))}
        </ul>
      </div>
      <div className="space-y-3">
        <form onSubmit={(e) => { e.preventDefault(); if (note.trim()) act(() => api.note(pid, note.trim())).then(() => setNote("")); }}>
          <h3 className="mb-1 text-xs font-semibold text-slate-700 dark:text-slate-200">Add note</h3>
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} className={field} placeholder="Clinical note (pseudonymous record)…" aria-label="clinical note" />
          <button type="submit" className="mt-1 flex items-center gap-1 rounded bg-brand px-2 py-0.5 text-xs text-white"><Send className="h-3 w-3" aria-hidden /> Save note</button>
        </form>
        <form onSubmit={(e) => { e.preventDefault(); act(() => api.intervention(pid, kind, detail)).then(() => setDetail("")); }}>
          <h3 className="mb-1 text-xs font-semibold text-slate-700 dark:text-slate-200">Suggest intervention</h3>
          <select value={kind} onChange={(e) => setKind(e.target.value)} className={field} aria-label="intervention type">
            {KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
          <input value={detail} onChange={(e) => setDetail(e.target.value)} className={`${field} mt-1`} placeholder="Details (e.g. swap white rice for millet)" aria-label="intervention details" />
          <button type="submit" className="mt-1 flex items-center gap-1 rounded bg-brand px-2 py-0.5 text-xs text-white"><ClipboardList className="h-3 w-3" aria-hidden /> Log suggestion</button>
        </form>
        <ul className="max-h-28 space-y-1 overflow-y-auto text-[11px] text-slate-600 dark:text-slate-300">
          {d.notes.map((n, i) => <li key={i}><span className="font-mono text-slate-400">{fmtTime(n.ts)} {n.user}:</span> {n.text}</li>)}
        </ul>
      </div>
      <div>
        <h3 className="mb-2 text-xs font-semibold text-slate-700 dark:text-slate-200">Audit trail (this patient)</h3>
        <ul className="max-h-64 space-y-1 overflow-y-auto font-mono text-[10px] text-slate-600 dark:text-slate-400">
          {audit.map((r) => (
            <li key={r.id} title={JSON.stringify(r.detail)}>
              <span className="text-slate-400">{r.ts_sim ? fmtDateTime(r.ts_sim) : r.ts_wall}</span> · {r.actor} · <span className="font-semibold">{r.action}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
