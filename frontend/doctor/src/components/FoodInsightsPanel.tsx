import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Circle } from "lucide-react";

interface Food {
  key: string; label: string; n: number; mean_rise: number; mean_peak: number; pct_above: number; mean_carbs: number;
  minutes_above: number; relative_to_usual: number | null; flag: "watch" | "ok"; confidence: string;
}
interface Insights {
  foods: Food[]; patterns: { key: string; text: string }[];
  symptom_links: { food: string; label: string; symptom: string; n: number; glucose_at_symptom: number | null; pattern: boolean; text: string }[];
  diary: { date: string; total_carbs: number; meals: number; late_meals: number; sweets: number; spikes_after_meals: number;
    items: { time: string; label: string; carbs: number; peak: number | null; went_above: boolean | null; watch: boolean }[] }[];
  usual_rise: number | null; meals_analysed: number; meals_logged: number; high: number; method: string;
}

/** Doctor view of the patient's daily consumption pattern and personal food / symptom associations. */
export function FoodInsightsPanel({ pid, tick }: { pid: string; tick?: string }) {
  const [f, setF] = useState<Insights | null>(null);
  const [day, setDay] = useState<number>(-1);
  useEffect(() => { fetch(`/api/patients/${pid}/food?user=dr.demo`).then((r) => r.json()).then(setF).catch(() => undefined); }, [pid, tick]);
  if (!f) return <p className="text-sm text-slate-500">Loading food insights…</p>;
  const d = f.diary.at(day) ?? f.diary[f.diary.length - 1];
  return (
    <div className="grid gap-4 xl:grid-cols-[1.2fr_1fr]">
      <div>
        <p className="mb-2 text-xs text-slate-500">
          {f.meals_analysed} of {f.meals_logged} logged meals analysed (meals followed by another within 90 min excluded) · usual rise after a meal {f.usual_rise ?? "–"} mg/dL
        </p>
        <table className="w-full text-xs">
          <thead className="text-left text-slate-500"><tr><th>Food</th><th>n</th><th>Mean rise</th><th>Mean peak</th><th>&gt;{f.high}</th><th>vs usual</th><th>Evidence</th></tr></thead>
          <tbody>
            {f.foods.map((x) => (
              <tr key={x.key} className={x.flag === "watch" ? "bg-amber-50 font-semibold dark:bg-amber-950/40" : ""}>
                <td className="flex items-center gap-1 py-0.5">
                  {x.flag === "watch" ? <AlertTriangle aria-label="watch: worse than usual" className="h-3 w-3 text-amber-600" />
                    : x.mean_peak <= f.high ? <CheckCircle2 aria-label="peak within target" className="h-3 w-3 text-risk-green" />
                    : <Circle aria-label="high but not worse than usual" className="h-3 w-3 text-slate-400" />}
                  {x.label}
                </td>
                <td>{x.n}</td><td>+{x.mean_rise}</td><td>{x.mean_peak}</td><td>{x.pct_above}%</td>
                <td>{x.relative_to_usual != null ? `${x.relative_to_usual}×` : "–"}</td><td>{x.confidence}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {f.patterns.length > 0 && <ul className="mt-2 list-disc pl-4 text-xs">{f.patterns.map((p) => <li key={p.key}>{p.text}</li>)}</ul>}
        {f.symptom_links.length > 0 && (
          <div className="mt-2 text-xs">
            <p className="font-semibold">Symptoms reported after foods (4 h window)</p>
            <ul className="list-disc pl-4">{f.symptom_links.map((s) => <li key={`${s.food}-${s.symptom}`} className={s.pattern ? "font-semibold" : ""}>{s.text}</li>)}</ul>
          </div>
        )}
        <p className="mt-2 text-[10px] text-slate-500">⚠ watch = consistently high and worse than this patient's usual meal · ✓ peak within target · ○ high but not worse than usual.
          Per-patient association from the twin's CGM after each logged meal. Not causal proof; small n is flagged by evidence level.</p>
      </div>
      <div>
        <div className="mb-1 flex flex-wrap gap-1" role="group" aria-label="Diary day">
          {f.diary.map((x, i) => (
            <button key={x.date} onClick={() => setDay(i)} aria-pressed={x.date === d.date}
              className={`rounded border px-1.5 py-0.5 text-[11px] ${x.date === d.date ? "border-brand bg-brand text-white" : "border-slate-300 dark:border-slate-600"}`}>
              {x.date.slice(5)}
            </button>
          ))}
        </div>
        <p className="text-xs text-slate-500">{d.meals} meals · {d.total_carbs} g carbs · {d.spikes_after_meals} above {f.high} after a meal · {d.late_meals} late · {d.sweets} sweets</p>
        <ul className="mt-1 space-y-0.5 font-mono text-xs">
          {d.items.map((i, k) => (
            <li key={k} className={i.watch ? "text-amber-700 dark:text-amber-300" : ""}>
              {i.time} {i.watch ? "⚠ " : ""}{i.label}: {i.carbs} g{i.peak != null && ` → peak ${i.peak}${i.went_above ? " (high)" : ""}`}
            </li>
          ))}
          {d.items.length === 0 && <li className="text-slate-500">No meals logged.</li>}
        </ul>
      </div>
    </div>
  );
}
