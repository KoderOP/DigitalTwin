import { useEffect, useState } from "react";
import { Lock, Rocket, X } from "lucide-react";
import { portal, PortalError, type PortalConfig } from "./portalApi";

const DIET: Record<string, string> = {
  swap_rice_millet: "Swap white rice for millet / roti", half_plate_veg: "Half plate vegetables", early_dinner: "Dinner before 8 pm",
  limit_sweets: "Sweets only on special days", less_sugar_chai: "Chai with less sugar", protein_breakfast: "Protein at breakfast",
};
const STEPS = ["Template", "Language & targets", "Features & care plan", "Alerts & contacts", "Preview & launch"];

/**
 * Launch / edit wizard. Template defaults (personalised from the EHR) make it a < 2-minute flow:
 * Next -> Next -> Next -> Save & preview -> Launch. Bounds are validated server-side (422 shown inline).
 */
export function LaunchWizard({ pid, initial, mode, onClose, onDone }: {
  pid: string; initial: PortalConfig | null; mode: "launch" | "edit"; onClose: () => void; onDone: () => void;
}) {
  const [step, setStep] = useState(0);
  const [templates, setTemplates] = useState<Record<string, { label: string }>>({});
  const [cfg, setCfg] = useState<PortalConfig | null>(initial);
  const [err, setErr] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [started] = useState(() => Date.now());

  useEffect(() => { portal.templates().then(setTemplates).catch(() => undefined); }, []);
  useEffect(() => { if (!initial) void pickTemplate("standard"); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function pickTemplate(name: string) {
    setCfg(await portal.templateConfig(pid, name));
  }
  const upd = (fn: (c: PortalConfig) => void) => setCfg((c) => { if (!c) return c; const n = structuredClone(c); fn(n); return n; });

  async function saveAndPreview() {
    if (!cfg) return;
    setBusy(true);
    setErr(null);
    try {
      await portal.enroll(pid, cfg.template);
      await portal.saveConfig(pid, cfg);
      const p = await portal.previewToken(pid);
      setPreview(p.path);
      setStep(4);
    } catch (e) {
      setErr(e instanceof PortalError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function launch() {
    setBusy(true);
    try {
      if (mode === "launch") await portal.launch(pid);
      onDone();
    } catch (e) {
      setErr(e instanceof PortalError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const field = "rounded border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-800";
  return (
    <div role="dialog" aria-modal="true" aria-label="Launch patient interface" className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4">
      <div className="w-full max-w-4xl rounded-xl bg-white p-5 shadow-xl dark:bg-slate-900">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-bold">{mode === "launch" ? "Launch patient interface" : "Edit patient interface"} · <span className="font-mono">{pid}</span></h2>
          <button onClick={onClose} aria-label="Close"><X className="h-5 w-5" /></button>
        </div>
        <ol className="mb-4 flex flex-wrap gap-2 text-xs">
          {STEPS.map((s, i) => (
            <li key={s} className={`rounded-full px-3 py-1 ${i === step ? "bg-brand text-white" : i < step ? "bg-sky-100 text-sky-900" : "bg-slate-100 text-slate-500 dark:bg-slate-800"}`}>{i + 1}. {s}</li>
          ))}
        </ol>
        {!cfg ? <p>Loading template…</p> : (
          <div className="min-h-64 text-sm">
            {step === 0 && (
              <div className="grid gap-2 md:grid-cols-2">
                {Object.entries(templates).map(([k, v]) => (
                  <button key={k} onClick={() => pickTemplate(k)} aria-pressed={cfg.template === k}
                    className={`rounded-lg border-2 p-3 text-left ${cfg.template === k ? "border-brand bg-sky-50 dark:bg-slate-800" : "border-slate-200 dark:border-slate-700"}`}>
                    <p className="font-semibold">{v.label}</p><p className="text-xs text-slate-500">template: {k}</p>
                  </button>
                ))}
                <p className="text-xs text-slate-500 md:col-span-2">Medication reminders are pre-filled from the EHR prescription (reminders only; the app never changes doses).</p>
              </div>
            )}
            {step === 1 && (
              <div className="space-y-3">
                <fieldset><legend className="font-semibold">Patient language</legend>
                  {(["en", "hi", "ta"] as const).map((l) => (
                    <label key={l} className="mr-4"><input type="radio" checked={cfg.language === l} onChange={() => upd((c) => { c.language = l; })} /> {{ en: "English", hi: "हिन्दी (Hindi)", ta: "தமிழ் (Tamil)" }[l]}</label>
                  ))}
                </fieldset>
                <fieldset className="flex flex-wrap items-center gap-3"><legend className="font-semibold">Target range (mg/dL)</legend>
                  <label>Low <input type="number" className={`${field} w-20`} value={cfg.target.low} min={70} max={100} onChange={(e) => upd((c) => { c.target.low = +e.target.value; })} /></label>
                  <label>High <input type="number" className={`${field} w-20`} value={cfg.target.high} min={140} max={200} onChange={(e) => upd((c) => { c.target.high = +e.target.value; })} /></label>
                  <span className="text-xs text-slate-500">Allowed: low 70–100, high 140–200, span ≥ 60. Default 70–180.</span>
                </fieldset>
                <label className="block"><span className="font-semibold">Patient "watch" notification sensitivity</span>: notify when spike probability ≥{" "}
                  <input type="range" min={0.25} max={0.9} step={0.05} value={cfg.alerts.amber_threshold} onChange={(e) => upd((c) => { c.alerts.amber_threshold = +e.target.value; })} />{" "}
                  <b>{Math.round(cfg.alerts.amber_threshold * 100)}%</b> <span className="text-xs text-slate-500">(allowed 25–90%)</span></label>
                <p className="flex items-center gap-2 rounded bg-slate-100 p-2 text-xs dark:bg-slate-800"><Lock aria-hidden className="h-4 w-4" />
                  RED spike alerts and low-glucose (&lt; 70 mg/dL, predicted or detected) alerts are <b>always on</b> and cannot be disabled or capped.</p>
              </div>
            )}
            {step === 2 && (
              <div className="grid gap-4 md:grid-cols-2">
                <fieldset className="space-y-1"><legend className="font-semibold">Features</legend>
                  {(["quick_log", "try_it", "progress", "caregiver"] as const).map((f) => (
                    <label key={f} className="block"><input type="checkbox" checked={cfg.features[f]} onChange={(e) => upd((c) => { c.features[f] = e.target.checked; })} /> {{ quick_log: "Quick Log", try_it: "Try-It what-if", progress: "Progress", caregiver: "Caregiver view (needs patient consent)" }[f]}</label>
                  ))}
                </fieldset>
                <fieldset className="space-y-1"><legend className="font-semibold">Diet guidance</legend>
                  {Object.entries(DIET).map(([k, v]) => (
                    <label key={k} className="block"><input type="checkbox" checked={cfg.care_plan.diet.includes(k)}
                      onChange={(e) => upd((c) => { c.care_plan.diet = e.target.checked ? [...c.care_plan.diet, k] : c.care_plan.diet.filter((d) => d !== k); })} /> {v}</label>
                  ))}
                </fieldset>
                <fieldset className="space-y-2"><legend className="font-semibold">Exercise goals</legend>
                  <label className="block">Steps / day <input type="number" className={`${field} w-24`} min={2000} max={15000} step={500} value={cfg.care_plan.steps_goal} onChange={(e) => upd((c) => { c.care_plan.steps_goal = +e.target.value; })} /></label>
                  <label className="block"><input type="checkbox" checked={cfg.care_plan.post_meal_walk} onChange={(e) => upd((c) => { c.care_plan.post_meal_walk = e.target.checked; })} /> Post-meal walk of{" "}
                    <input type="number" className={`${field} w-16`} min={5} max={60} value={cfg.care_plan.walk_minutes} onChange={(e) => upd((c) => { c.care_plan.walk_minutes = +e.target.value; })} /> min</label>
                </fieldset>
                <fieldset className="space-y-1"><legend className="font-semibold">Medication reminders (existing prescription only)</legend>
                  {cfg.care_plan.medication_reminders.map((r, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <input className={`${field} flex-1`} value={r.label} onChange={(e) => upd((c) => { c.care_plan.medication_reminders[i].label = e.target.value; })} aria-label="reminder label" />
                      <input type="time" className={field} value={r.time} onChange={(e) => upd((c) => { c.care_plan.medication_reminders[i].time = e.target.value; })} aria-label="reminder time" />
                      <button onClick={() => upd((c) => { c.care_plan.medication_reminders.splice(i, 1); })} aria-label="remove">✕</button>
                    </div>
                  ))}
                  <button className="text-xs text-brand underline" onClick={() => upd((c) => { c.care_plan.medication_reminders.push({ label: "Medicine (as prescribed)", time: "09:00" }); })}>+ add reminder</button>
                </fieldset>
              </div>
            )}
            {step === 3 && (
              <div className="space-y-3">
                <div className="flex flex-wrap gap-4">
                  <label>Max non-safety notifications / day <input type="number" className={`${field} w-16`} min={1} max={8} value={cfg.alerts.daily_cap} onChange={(e) => upd((c) => { c.alerts.daily_cap = +e.target.value; })} /></label>
                  <label>Min gap (min) <input type="number" className={`${field} w-20`} min={30} max={240} value={cfg.alerts.min_gap_min} onChange={(e) => upd((c) => { c.alerts.min_gap_min = +e.target.value; })} /></label>
                  <label>Escalate unacknowledged safety alerts after (min) <input type="number" className={`${field} w-20`} min={10} max={120} value={cfg.alerts.escalate_after_min} onChange={(e) => upd((c) => { c.alerts.escalate_after_min = +e.target.value; })} /></label>
                </div>
                <fieldset className="space-y-1"><legend className="font-semibold">Escalation contacts (fictional demo contacts only, max 3)</legend>
                  {cfg.alerts.escalation_contacts.map((ct, i) => (
                    <div key={i} className="flex flex-wrap items-center gap-2">
                      <input className={field} placeholder="name" value={ct.name} onChange={(e) => upd((c) => { c.alerts.escalation_contacts[i].name = e.target.value; })} />
                      <input className={`${field} w-24`} placeholder="relation" value={ct.relation} onChange={(e) => upd((c) => { c.alerts.escalation_contacts[i].relation = e.target.value; })} />
                      <select className={field} value={ct.channel} onChange={(e) => upd((c) => { c.alerts.escalation_contacts[i].channel = e.target.value as "sms" | "email"; })}><option value="sms">SMS (mock)</option><option value="email">Email (mock)</option></select>
                      <input className={field} placeholder="+91-00000-00000" value={ct.handle} onChange={(e) => upd((c) => { c.alerts.escalation_contacts[i].handle = e.target.value; })} />
                      <button onClick={() => upd((c) => { c.alerts.escalation_contacts.splice(i, 1); })} aria-label="remove contact">✕</button>
                    </div>
                  ))}
                  {cfg.alerts.escalation_contacts.length < 3 && (
                    <button className="text-xs text-brand underline" onClick={() => upd((c) => { c.alerts.escalation_contacts.push({ name: "Demo Family", relation: "family", channel: "sms", handle: "+91-00000-00000" }); })}>+ add contact</button>
                  )}
                </fieldset>
              </div>
            )}
            {step === 4 && preview && (
              <div className="grid gap-4 md:grid-cols-[1fr_380px]">
                <div className="space-y-2">
                  <p className="font-semibold">Configuration saved. On the right is exactly what the patient will see.</p>
                  <ul className="list-disc pl-5 text-xs">
                    <li>Language: {cfg.language} · target {cfg.target.low}–{cfg.target.high} mg/dL · watch at ≥ {Math.round(cfg.alerts.amber_threshold * 100)}%</li>
                    <li>Features: {Object.entries(cfg.features).filter(([, v]) => v).map(([k]) => k).join(", ")}</li>
                    <li>Care plan: {cfg.care_plan.diet.length} diet items, {cfg.care_plan.steps_goal} steps/day, {cfg.care_plan.medication_reminders.length} reminders</li>
                    <li>Notification cap {cfg.alerts.daily_cap}/day, gap {cfg.alerts.min_gap_min} min; safety alerts always on</li>
                  </ul>
                  <p className="text-xs text-slate-500">Wizard time so far: {Math.round((Date.now() - started) / 1000)} s</p>
                  <button disabled={busy} onClick={launch} className="flex items-center gap-2 rounded-lg bg-brand px-4 py-2 font-semibold text-white disabled:opacity-50">
                    <Rocket className="h-4 w-4" aria-hidden /> {mode === "launch" ? "Launch & create secure invite" : "Done"}
                  </button>
                </div>
                <iframe title="Patient preview" src={preview} className="h-[640px] w-full rounded-xl border-4 border-slate-800" />
              </div>
            )}
          </div>
        )}
        {err && <p role="alert" className="mt-2 rounded bg-red-50 p-2 text-sm text-red-800">{err}</p>}
        <div className="mt-4 flex justify-between">
          <button disabled={step === 0} onClick={() => setStep((s) => s - 1)} className="rounded border px-3 py-1 text-sm disabled:opacity-40">Back</button>
          {step < 3 && <button onClick={() => setStep((s) => s + 1)} className="rounded bg-brand px-3 py-1 text-sm font-semibold text-white">Next</button>}
          {step === 3 && <button disabled={busy} onClick={saveAndPreview} className="rounded bg-brand px-3 py-1 text-sm font-semibold text-white">Save & preview as patient</button>}
        </div>
      </div>
    </div>
  );
}
