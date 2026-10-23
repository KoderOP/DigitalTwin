import { useCallback, useEffect, useState } from "react";
import { Activity, AlertTriangle, Moon, Sun, UserRound, X } from "lucide-react";
import { portal, type Doctor } from "./portal/portalApi";
import { PatientInterfaceManager } from "./portal/PatientInterfaceManager";
import { DevOutbox } from "./portal/DevOutbox";
import type { PortalInfo } from "./components/CohortList";
import { FoodInsightsPanel } from "./components/FoodInsightsPanel";
import { api, useLive } from "./api";
import type { Meta } from "./types";
import { CohortList } from "./components/CohortList";
import { Card } from "@shared/components/Card";
import { CgmChart, timeDomain } from "./components/CgmChart";
import { RiskGauge, RiskHistory } from "./components/RiskGauge";
import { SignalsPanel } from "./components/SignalsPanel";
import { ExplainPanel } from "./components/ExplainPanel";
import { MetricsPanel } from "./components/MetricsPanel";
import { WhatIfPanel } from "./components/WhatIfPanel";
import { ClinicianPanel } from "./components/ClinicianPanel";
import { DemoControls } from "./components/DemoControls";
import { PatientHeader } from "./components/PatientHeader";
import { LevelBadge } from "@shared/components/LevelBadge";
import { fmtDateTime, num, pct } from "@shared/lib/format";

export const BANNER = "SYNTHETIC DATA ONLY: NOT FOR CLINICAL USE";

function useTheme(): [boolean, () => void] {
  const [dark, setDark] = useState(() => {
    try {
      const s = localStorage.getItem("theme");
      return s ? s === "dark" : window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
    } catch {
      return false;
    }
  });
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try { localStorage.setItem("theme", dark ? "dark" : "light"); } catch { /* storage unavailable */ }
  }, [dark]);
  return [dark, () => setDark((d) => !d)];
}

export default function App() {
  const [dark, toggleTheme] = useTheme();
  // deep link: /?patient=TWN-XXXXXX opens a twin directly (handy for demos)
  const [selected, setSelected] = useState<string | null>(() => new URLSearchParams(location.search).get("patient"));
  const { connected, state, cohort, detail, newAlerts, setDetail } = useLive(selected);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [toasts, setToasts] = useState<{ id: number; text: string; level?: string }[]>([]);

  const toast = useCallback((text: string, level?: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-3), { id, text, level }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000);
  }, []);

  useEffect(() => { api.meta().then(setMeta).catch(() => undefined); }, []);
  useEffect(() => {
    if (!selected && cohort.length) setSelected([...cohort].sort((a, b) => (b.risk ?? 0) - (a.risk ?? 0))[0].patient_id);
  }, [cohort, selected]);
  useEffect(() => { if (selected) api.patient(selected).then(setDetail).catch(() => undefined); }, [selected, setDetail]);
  useEffect(() => {
    newAlerts.forEach((a) => toast(`${a.level} alert for ${a.patient_id ?? ""}: P(spike) ${pct(a.risk)}${a.minutes_to_spike != null ? `, ~${a.minutes_to_spike} min` : ""}`, a.level));
  }, [newAlerts, toast]);

  // ---- patient-interface provisioning (doctor identity, statuses, bulk invite) ----
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [doctorId, setDoctorId] = useState<string | null>(null);
  const [portalRows, setPortalRows] = useState<Record<string, PortalInfo>>({});
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  useEffect(() => {
    portal.doctors().then(async (ds) => {
      setDoctors(ds);
      let want: string | null = null;
      try { want = localStorage.getItem("dt_doctor_id"); } catch { /* blocked */ }
      const id = ds.find((x) => x.id === want)?.id ?? ds[0]?.id;
      if (id) { await portal.login(id); setDoctorId(id); }
    }).catch(() => undefined);
  }, []);
  const loadPortal = useCallback(() => {
    if (!doctorId) return;
    portal.status().then((rows) => setPortalRows(Object.fromEntries(rows.map((r) => [r.patient_id, { state: r.state, assigned_to_me: r.assigned_to_me }])))).catch(() => undefined);
  }, [doctorId]);
  useEffect(() => { loadPortal(); }, [loadPortal, state?.clock]);
  const bulk = {
    picked, busy: bulkBusy,
    toggle: (id: string) => setPicked((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; }),
    invite: async () => {
      setBulkBusy(true);
      try {
        const res = await portal.bulkInvite([...picked], "standard");
        toast(`Bulk invite: ${res.filter((r) => r.ok).length}/${res.length} invites created (links in each patient's panel and the dev outbox)`);
        setPicked(new Set());
        loadPortal();
      } finally { setBulkBusy(false); }
    },
    newPatient: async () => {
      setBulkBusy(true);
      try {
        const m = await portal.newPatient("standard");
        toast(`New synthetic patient ${m.patient_id} enrolled (twin instantiated from a fresh synthetic EHR)`);
        loadPortal();
        setSelected(m.patient_id);
      } catch (e) { toast(`Error: ${String(e)}`); } finally { setBulkBusy(false); }
    },
  };

  const refresh = () => selected && api.patient(selected).then(setDetail);
  const d = detail && detail.header.patient_id === selected ? detail : null;
  const dom = d ? timeDomain(d) : null;

  return (
    <div className="flex min-h-screen flex-col text-slate-800 dark:text-slate-100">
      <div role="alert" className="bg-[repeating-linear-gradient(45deg,#E69F00_0_12px,#f3b53a_12px_24px)] px-3 py-1 text-center text-xs font-bold tracking-wide text-black">
        <AlertTriangle className="mr-1 inline h-3 w-3" aria-hidden /> {BANNER}: research prototype, simulated patients, not a medical device
      </div>
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-white px-4 py-2 dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center gap-2">
          <Activity className="h-5 w-5 text-brand" aria-hidden />
          <div>
            <p className="text-sm font-bold">T2D Digital Twin</p>
            <p className="text-[11px] text-slate-500">Hyperglycemia early warning (&gt;180 mg/dL, 2 h ahead) · EHR + wearable fusion</p>
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <label className="flex items-center gap-1">
            <UserRound className="h-4 w-4" aria-hidden /> <span className="sr-only">Signed-in doctor</span>
            <select value={doctorId ?? ""} onChange={async (e) => { await portal.login(e.target.value); setDoctorId(e.target.value); }}
              className="rounded border border-slate-300 bg-white px-1 py-0.5 dark:border-slate-700 dark:bg-slate-800" aria-label="Signed-in doctor (demo)">
              {doctors.map((x) => <option key={x.id} value={x.id}>{x.name} (demo)</option>)}
            </select>
          </label>
          <span className="font-mono" aria-live="polite">Sim clock: <b>{state ? fmtDateTime(state.clock) : "…"}</b></span>
          <span className={`flex items-center gap-1 ${connected ? "text-risk-green" : "text-risk-red"}`}>
            <span className={`inline-block h-2 w-2 rounded-full ${connected ? "bg-risk-green" : "bg-risk-red"}`} aria-hidden />
            {connected ? "live" : "reconnecting"}
          </span>
          <button onClick={toggleTheme} aria-label={`Switch to ${dark ? "light" : "dark"} theme`} className="rounded-md border border-slate-300 p-1 dark:border-slate-700">
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
        </div>
      </header>
      <div className="border-b border-slate-200 bg-slate-100 px-4 py-2 dark:border-slate-800 dark:bg-slate-900/70">
        <DemoControls state={state} patientId={selected} onToast={(m) => toast(m)} />
      </div>

      <div className="flex flex-1 flex-col lg:flex-row">
        <aside className="max-h-[40vh] border-b border-slate-200 bg-white lg:max-h-none lg:w-72 lg:border-b-0 lg:border-r dark:border-slate-800 dark:bg-slate-900">
          <CohortList rows={cohort} selected={selected} onSelect={setSelected} portal={portalRows} bulk={doctorId ? bulk : undefined} />
        </aside>
        <main className="flex-1 space-y-4 p-4">
          {!d || !dom ? (
            <p className="text-sm text-slate-500">{connected ? "Select a patient to open their digital twin…" : "Connecting to the twin engine…"}</p>
          ) : (
            <>
              <Card><PatientHeader d={d} /></Card>
              {doctorId && (
                <Card title="Patient Interface Manager" subtitle="Doctor-initiated patient app: lifecycle, secure invite, settings, live preview and engagement">
                  <PatientInterfaceManager key={`${d.header.patient_id}-${doctorId}`} pid={d.header.patient_id} tick={state?.clock} onChanged={loadPortal} />
                </Card>
              )}
              <div className="grid gap-4 xl:grid-cols-[1fr_300px]">
                <Card title="Live CGM: last 12 h + 2 h forecast" subtitle="Black: CGM · blue dashed: forecast median · band: P10–P90 · green: target 70–180 · ▲ meal · ◆ medication · ! alert">
                  <CgmChart d={d} dom={dom} />
                  <p className="mt-2 text-[11px] font-medium text-slate-500">Predicted spike risk over time (AMBER and RED zones)</p>
                  <RiskHistory d={d} dom={dom} />
                </Card>
                <Card title="2-hour spike risk" right={d.prediction && <span className="text-[11px] text-slate-500">updated {fmtDateTime(d.prediction.ts)}</span>}>
                  {d.prediction ? <RiskGauge p={d.prediction} /> : <p className="text-sm">No prediction yet</p>}
                  {d.prediction && (
                    <table className="mt-3 w-full text-[11px]">
                      <thead className="text-slate-500"><tr><th className="text-left">Horizon</th><th>P10</th><th>P50</th><th>P90</th></tr></thead>
                      <tbody className="font-mono">
                        {d.prediction.forecast.map((f) => (
                          <tr key={f.minutes}><td>+{f.minutes} min</td><td className="text-center">{num(f.p10)}</td><td className="text-center font-semibold">{num(f.p50)}</td><td className="text-center">{num(f.p90)}</td></tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </Card>
              </div>
              <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
                <Card title="Wearable signals (shared time axis)" subtitle="Sleep stages, heart rate / HRV and steps from the smartwatch stream">
                  <SignalsPanel d={d} dom={dom} />
                </Card>
                <Card title="Why this alert?" subtitle="Top factors behind the current risk, from the EHR and the wearable stream"
                  right={d.prediction && <LevelBadge level={d.prediction.level} />}>
                  {d.prediction && <ExplainPanel p={d.prediction} />}
                </Card>
              </div>
              <div className="grid gap-4 xl:grid-cols-[minmax(0,420px)_1fr]">
                <Card title="Glycemic metrics" subtitle="Time in range, variability (CV), GMI and AGP-style daily summary">
                  <MetricsPanel d={d} />
                </Card>
                <Card title="What-if simulator" subtitle="Counterfactual trajectories from the personalised physiological twin">
                  <WhatIfPanel patientId={d.header.patient_id} />
                </Card>
              </div>
              <Card title="Food and symptom insights" subtitle="Daily consumption pattern and which foods push this patient's glucose up, measured from their own CGM">
                <FoodInsightsPanel pid={d.header.patient_id} tick={state?.clock} />
              </Card>
              <Card title="Clinician actions" subtitle="Every action is written to the audit trail with a pseudonymous user ID">
                <ClinicianPanel d={d} onChanged={refresh} />
              </Card>
            </>
          )}
        </main>
      </div>

      <footer className="border-t border-slate-200 bg-white px-4 py-3 text-[11px] text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
        <p className="font-semibold text-slate-800 dark:text-slate-200">Data provenance: {BANNER}</p>
        {meta ? (
          <div className="mt-1 grid gap-2 md:grid-cols-2">
            <ul className="list-disc pl-4">
              <li>EHR: {meta.provenance.ehr}</li>
              <li>Wearables / CGM: {meta.provenance.wearables}</li>
              <li>Synthea: {meta.provenance.synthea} · Open CGM datasets: {meta.provenance.open_cgm} · MIMIC-IV: {meta.provenance.mimic}</li>
              <li>Demo patients: {meta.provenance.demo_patients_from}. Generator v{meta.provenance.generator_version}, seed {meta.provenance.seed}.</li>
              <li>
                Model {meta.model}; held-out test ROC-AUC {num(meta.headline_test_metrics.roc_auc, 3)}, PR-AUC {num(meta.headline_test_metrics.pr_auc, 3)},
                alerts notified at {meta.headline_test_metrics.notify_level ?? "RED"}: mean lead {num(meta.headline_test_metrics.mean_lead_min)} min,
                {" "}{num(meta.headline_test_metrics.false_alerts_per_patient_day, 2)} false alerts/patient-day (see reports/evaluation_report.md). AMBER is a watch level only.
              </li>
            </ul>
            <ul className="list-disc pl-4">{meta.compliance.map((c) => <li key={c}>{c}</li>)}</ul>
          </div>
        ) : <p>Loading provenance…</p>}
      </footer>

      {doctorId && <DevOutbox onNew={toast} />}
      <div className="fixed bottom-4 right-4 z-50 space-y-2" aria-live="assertive">
        {toasts.map((t) => (
          <div key={t.id} className={`flex max-w-sm items-start gap-2 rounded-lg px-3 py-2 text-sm text-white shadow-lg ${t.level === "RED" ? "bg-risk-red" : t.level === "AMBER" ? "bg-amber-700" : "bg-slate-800"}`}>
            {t.level && <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />}
            <span className="flex-1">{t.text}</span>
            <button onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))} aria-label="dismiss"><X className="h-4 w-4" /></button>
          </div>
        ))}
      </div>
    </div>
  );
}
