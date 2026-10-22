import { useState } from "react";
import { FlaskConical, Play, Plus, Trash2 } from "lucide-react";
import { CartesianGrid, Legend, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import type { Intervention, ScenarioReq, WhatIfResult } from "../types";
import { COLORS, fmtTime, ms, num } from "../lib/format";

const SERIES = [
  { color: COLORS.blue, dash: undefined },
  { color: COLORS.red, dash: "8 3" },
  { color: COLORS.green, dash: "2 2" },
  { color: COLORS.high, dash: "10 3 2 3" },
];

export const PRESETS: { label: string; scenarios: ScenarioReq[] }[] = [
  { label: "Walk 20 min now", scenarios: [{ name: "Brisk walk 20 min now", interventions: [{ type: "exercise", minutes: 20, intensity: "moderate", in_min: 0 }] }] },
  { label: "Metformin 500 mg now", scenarios: [{ name: "Metformin 500 mg now", interventions: [{ type: "medication", drug: "metformin", dose: 500, in_min: 0 }] }] },
  {
    label: "60 g dinner 19:00 vs 21:00",
    scenarios: [
      { name: "60 g dinner at 19:00", interventions: [{ type: "meal", carbs: 60, gi: "medium", at: "19:00" }] },
      { name: "60 g dinner at 21:00", interventions: [{ type: "meal", carbs: 60, gi: "medium", at: "21:00" }] },
    ],
  },
  {
    label: "Sleep 5 h vs 8 h",
    scenarios: [
      { name: "Sleeps 5 h", interventions: [{ type: "sleep", hours: 5 }] },
      { name: "Sleeps 8 h", interventions: [{ type: "sleep", hours: 8 }] },
    ],
  },
  {
    label: "Rice meal: walk after vs not",
    scenarios: [
      { name: "80 g rice meal now", interventions: [{ type: "meal", carbs: 80, gi: "high", in_min: 0 }] },
      { name: "80 g rice meal + 20 min walk after 15 min", interventions: [{ type: "meal", carbs: 80, gi: "high", in_min: 0 }, { type: "exercise", minutes: 20, intensity: "moderate", in_min: 15 }] },
    ],
  },
];

interface Builder {
  meal: boolean; carbs: number; gi: "low" | "medium" | "high"; mealAt: string;
  ex: boolean; exMin: number; intensity: "light" | "moderate" | "vigorous"; exIn: number;
  med: boolean; drug: "metformin" | "sulfonylurea" | "rapid_insulin"; dose: number;
  sleep: boolean; hours: number;
}

export function buildScenario(b: Builder): ScenarioReq {
  const iv: Intervention[] = [];
  const parts: string[] = [];
  if (b.meal) {
    iv.push({ type: "meal", carbs: b.carbs, gi: b.gi, ...(b.mealAt ? { at: b.mealAt } : { in_min: 0 }) });
    parts.push(`${b.carbs} g ${b.gi}-GI meal ${b.mealAt ? `at ${b.mealAt}` : "now"}`);
  }
  if (b.ex) {
    iv.push({ type: "exercise", minutes: b.exMin, intensity: b.intensity, in_min: b.exIn });
    parts.push(`${b.exMin} min ${b.intensity} exercise${b.exIn ? ` in ${b.exIn} min` : " now"}`);
  }
  if (b.med) {
    iv.push({ type: "medication", drug: b.drug, dose: b.dose, in_min: 0 });
    parts.push(`${b.drug.replace("_", " ")} ${b.dose}${b.drug === "rapid_insulin" ? " U" : " mg"}`);
  }
  if (b.sleep) {
    iv.push({ type: "sleep", hours: b.hours });
    parts.push(`sleep ${b.hours} h`);
  }
  return { name: parts.join(" + ") || "No change", interventions: iv };
}

const DEFAULT: Builder = { meal: true, carbs: 60, gi: "medium", mealAt: "", ex: false, exMin: 20, intensity: "moderate", exIn: 0, med: false, drug: "metformin", dose: 500, sleep: false, hours: 5 };

export function WhatIfPanel({ patientId }: { patientId: string }) {
  const [b, setB] = useState<Builder>(DEFAULT);
  const [queue, setQueue] = useState<ScenarioReq[]>([]);
  const [res, setRes] = useState<WhatIfResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const set = <K extends keyof Builder>(k: K, v: Builder[K]) => setB((x) => ({ ...x, [k]: v }));

  const run = async (scenarios: ScenarioReq[]) => {
    setBusy(true);
    setErr(null);
    try {
      setRes(await api.whatIf(patientId, scenarios));
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const data = res
    ? res.times.map((t, i) => ({ t: ms(t), baseline: res.baseline.trajectory[i], ...Object.fromEntries(res.scenarios.map((s, k) => [`s${k}`, s.trajectory[i]])) }))
    : [];
  const inputCls = "rounded border border-slate-300 bg-white px-1 py-0.5 text-xs dark:border-slate-700 dark:bg-slate-800";

  return (
    <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
      <div className="space-y-3 text-xs">
        <div>
          <p className="mb-1 font-semibold text-slate-700 dark:text-slate-200">Quick scenarios</p>
          <div className="flex flex-wrap gap-1">
            {PRESETS.map((p) => (
              <button key={p.label} disabled={busy} onClick={() => run(p.scenarios)} className="rounded-md border border-brand px-2 py-1 text-brand hover:bg-brand hover:text-white disabled:opacity-50 dark:text-sky-300">
                {p.label}
              </button>
            ))}
          </div>
        </div>
        <fieldset className="space-y-2 rounded-lg border border-slate-200 p-2 dark:border-slate-700">
          <legend className="px-1 font-semibold text-slate-700 dark:text-slate-200">Build a scenario</legend>
          <label className="flex items-center gap-2"><input type="checkbox" checked={b.meal} onChange={(e) => set("meal", e.target.checked)} /> Meal</label>
          {b.meal && (
            <div className="ml-5 space-y-1">
              <label className="flex items-center gap-2">Carbs <input type="range" min={10} max={150} step={5} value={b.carbs} onChange={(e) => set("carbs", +e.target.value)} aria-label="carbohydrates in grams" /> <span className="font-mono">{b.carbs} g</span></label>
              <label className="flex items-center gap-2">GI
                <select className={inputCls} value={b.gi} onChange={(e) => set("gi", e.target.value as Builder["gi"])}><option value="low">low (millet, dal)</option><option value="medium">medium (roti)</option><option value="high">high (white rice, idli)</option></select>
              </label>
              <label className="flex items-center gap-2">At <input type="time" className={inputCls} value={b.mealAt} onChange={(e) => set("mealAt", e.target.value)} /> <span className="text-slate-500">(empty = now)</span></label>
            </div>
          )}
          <label className="flex items-center gap-2"><input type="checkbox" checked={b.ex} onChange={(e) => set("ex", e.target.checked)} /> Exercise</label>
          {b.ex && (
            <div className="ml-5 space-y-1">
              <label className="flex items-center gap-2">Duration <input type="range" min={5} max={90} step={5} value={b.exMin} onChange={(e) => set("exMin", +e.target.value)} aria-label="exercise minutes" /> <span className="font-mono">{b.exMin} min</span></label>
              <label className="flex items-center gap-2">Intensity
                <select className={inputCls} value={b.intensity} onChange={(e) => set("intensity", e.target.value as Builder["intensity"])}><option>light</option><option>moderate</option><option>vigorous</option></select>
              </label>
              <label className="flex items-center gap-2">Start in <input type="number" min={0} max={600} step={5} className={`${inputCls} w-16`} value={b.exIn} onChange={(e) => set("exIn", +e.target.value)} /> min</label>
            </div>
          )}
          <label className="flex items-center gap-2"><input type="checkbox" checked={b.med} onChange={(e) => set("med", e.target.checked)} /> Medication now</label>
          {b.med && (
            <div className="ml-5 flex items-center gap-2">
              <select className={inputCls} value={b.drug} onChange={(e) => { const d = e.target.value as Builder["drug"]; setB((x) => ({ ...x, drug: d, dose: d === "metformin" ? 500 : d === "sulfonylurea" ? 2 : 6 })); }}>
                <option value="metformin">Metformin (mg)</option><option value="sulfonylurea">Glimepiride (mg)</option><option value="rapid_insulin">Rapid insulin (U)</option>
              </select>
              <input type="number" className={`${inputCls} w-20`} value={b.dose} min={0} onChange={(e) => set("dose", +e.target.value)} aria-label="dose" />
            </div>
          )}
          <label className="flex items-center gap-2"><input type="checkbox" checked={b.sleep} onChange={(e) => set("sleep", e.target.checked)} /> Sleep</label>
          {b.sleep && (
            <label className="ml-5 flex items-center gap-2">Hours <input type="range" min={3} max={10} step={0.5} value={b.hours} onChange={(e) => set("hours", +e.target.value)} aria-label="sleep hours" /> <span className="font-mono">{b.hours} h</span></label>
          )}
          <div className="flex gap-2 pt-1">
            <button disabled={busy} onClick={() => run([...queue, buildScenario(b)])} className="flex items-center gap-1 rounded-md bg-brand px-2 py-1 font-medium text-white disabled:opacity-50"><Play className="h-3 w-3" aria-hidden /> Simulate</button>
            <button disabled={queue.length >= 3} onClick={() => setQueue((q) => [...q, buildScenario(b)])} className="flex items-center gap-1 rounded-md border border-slate-300 px-2 py-1 dark:border-slate-600"><Plus className="h-3 w-3" aria-hidden /> Add for comparison</button>
          </div>
          {queue.length > 0 && (
            <ul className="space-y-0.5 text-[11px] text-slate-600 dark:text-slate-300">
              {queue.map((q, i) => (<li key={i} className="flex items-center justify-between">{q.name}<button aria-label="remove" onClick={() => setQueue((x) => x.filter((_, k) => k !== i))}><Trash2 className="h-3 w-3" /></button></li>))}
            </ul>
          )}
        </fieldset>
      </div>
      <div>
        {!res && !busy && (
          <div className="flex h-full min-h-48 flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 dark:border-slate-700">
            <FlaskConical className="mb-2 h-6 w-6" aria-hidden />
            Pick a quick scenario or build one. The personalised twin simulates the glucose trajectory from the patient's current state and compares it with the baseline.
          </div>
        )}
        {busy && <p className="text-sm text-slate-500">Simulating…</p>}
        {err && <p className="text-sm text-risk-red">{err}</p>}
        {res && (
          <>
            <div className="h-64" role="img" aria-label="What-if simulated glucose trajectories">
              <ResponsiveContainer>
                <LineChart data={data} margin={{ top: 6, right: 12, bottom: 0, left: -12 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-slate-200 dark:text-slate-800" />
                  <ReferenceArea y1={70} y2={180} fill={COLORS.green} fillOpacity={0.08} />
                  <ReferenceLine y={180} stroke={COLORS.red} strokeDasharray="5 4" />
                  <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} tickFormatter={fmtTime} fontSize={10} />
                  <YAxis domain={[40, "dataMax + 20"]} fontSize={10} />
                  <Tooltip labelFormatter={(t) => fmtTime(t as number)} formatter={(v: number) => `${v} mg/dL`} contentStyle={{ fontSize: 12 }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Line dataKey="baseline" name={res.baseline.name} stroke={COLORS.grey} strokeDasharray="4 4" dot={false} strokeWidth={2} isAnimationActive={false} />
                  {res.scenarios.map((s, k) => (
                    <Line key={k} dataKey={`s${k}`} name={s.name} stroke={SERIES[k % 4].color} strokeDasharray={SERIES[k % 4].dash} dot={false} strokeWidth={2} isAnimationActive={false} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
            <table className="mt-2 w-full text-xs">
              <thead className="text-slate-500"><tr><th className="text-left">Scenario</th><th>Peak</th><th>Min &gt;180</th><th>Δ peak</th><th>Δ min &gt;180</th><th>Min &lt;70</th></tr></thead>
              <tbody className="font-mono text-slate-700 dark:text-slate-200">
                <tr><td className="font-sans">{res.baseline.name}</td><td className="text-center">{num(res.baseline.summary.peak)}</td><td className="text-center">{res.baseline.summary.minutes_above_180}</td><td className="text-center">–</td><td className="text-center">–</td><td className="text-center">{res.baseline.summary.minutes_below_70}</td></tr>
                {res.scenarios.map((s, k) => (
                  <tr key={k}><td className="font-sans" style={{ color: SERIES[k % 4].color }}>{s.name}</td><td className="text-center">{num(s.summary.peak)}</td><td className="text-center">{s.summary.minutes_above_180}</td>
                    <td className="text-center">{s.summary.delta_peak > 0 ? "+" : ""}{num(s.summary.delta_peak)}</td><td className="text-center">{s.summary.delta_minutes_above_180 > 0 ? "+" : ""}{s.summary.delta_minutes_above_180}</td><td className="text-center">{s.summary.minutes_below_70}</td></tr>
                ))}
              </tbody>
            </table>
            <ul className="mt-2 list-disc pl-4 text-[11px] text-slate-500">
              {res.notes.map((n) => <li key={n}>{n}</li>)}
              <li>Twin personalisation: insulin sensitivity x{res.simulator.si_mult}, basal set-point x{res.simulator.gb_mult} vs EHR prior (calibration RMSE {num(res.simulator.calibration_rmse, 1)} mg/dL).</li>
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
