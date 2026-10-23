import { useTranslation } from "react-i18next";
import { AlertTriangle, CheckCircle2, Lightbulb, NotebookPen, Utensils } from "lucide-react";
import type { FoodInsights } from "../types";
import { Panel } from "./ui";

/** Daily consumption pattern + which foods push *this* patient's sugar up (from their own sensor data). */
export function FoodPatterns({ f }: { f: FoodInsights }) {
  const { t } = useTranslation();
  const watch = f.foods.filter((x) => x.flag === "watch");
  // "fine" only when the average peak stays within target (not merely "no worse than usual")
  const fine = f.foods.filter((x) => x.flag === "ok" && x.n >= 2 && x.mean_peak <= f.high).slice(0, 3);
  const today = f.diary[f.diary.length - 1];
  return (
    <Panel title={<span className="flex items-center gap-2"><Utensils aria-hidden className="h-5 w-5" />{t("foodai.title")}</span>}>
      {f.meals_logged === 0 ? <p>{t("foodai.empty")}</p> : (
        <div className="space-y-4">
          {watch.length > 0 && (
            <section aria-label={t("foodai.watch_list")}>
              <h3 className="mb-2 font-semibold">{t("foodai.watch_list")}</h3>
              <ul className="space-y-2" data-testid="food-watch">
                {watch.map((x) => (
                  <li key={x.key} className="rounded-xl border-2 border-amber-500 p-3">
                    <p className="flex items-center gap-2 text-base font-bold">
                      <AlertTriangle aria-hidden className="h-5 w-5 text-amber-600" /> {x.label}
                      <span className="rounded-full bg-amber-100 px-2 text-xs font-semibold text-amber-900">{t("foodai.watch")}</span>
                    </p>
                    <p className="text-base">{x.text}</p>
                    <p className="text-xs text-slate-500">{x.based_on} · {t(`foodai.confidence.${x.confidence}`)}</p>
                  </li>
                ))}
              </ul>
              <p className="mt-2 flex gap-2 text-sm"><Lightbulb aria-hidden className="h-5 w-5 shrink-0 text-brand" />{f.tip}</p>
            </section>
          )}
          {fine.length > 0 && (
            <ul className="space-y-1">
              {fine.map((x) => (
                <li key={x.key} className="flex items-center gap-2 text-sm"><CheckCircle2 aria-hidden className="h-4 w-4 text-risk-green" />
                  <b>{x.label}</b>: {t("foodai.ok")} ({t("foodai.peak")} {x.mean_peak}, {x.based_on})</li>
              ))}
            </ul>
          )}
          {f.patterns.length > 0 && (
            <section>
              <h3 className="mb-1 font-semibold">{t("foodai.patterns")}</h3>
              <ul className="ml-5 list-disc text-base">{f.patterns.map((p) => <li key={p.key}>{p.text}</li>)}</ul>
            </section>
          )}
          {f.symptom_links.length > 0 && (
            <section>
              <h3 className="mb-1 flex items-center gap-2 font-semibold"><NotebookPen aria-hidden className="h-5 w-5" />{t("foodai.symptoms")}</h3>
              <ul className="ml-5 list-disc text-base" data-testid="food-symptoms">
                {f.symptom_links.slice(0, 4).map((s) => <li key={`${s.food}-${s.symptom}`}>{s.text}</li>)}
              </ul>
            </section>
          )}
          <section>
            <h3 className="mb-1 font-semibold">{t("foodai.diary")}</h3>
            {today && today.items.length > 0 && (
              <ul className="mb-2 space-y-1 text-sm">
                {today.items.map((i, k) => (
                  <li key={k} className="flex items-center gap-2">
                    <span className="w-12 font-mono text-slate-500">{i.time}</span>
                    {i.watch && <AlertTriangle aria-label={t("foodai.watch")} className="h-4 w-4 text-amber-600" />}
                    <span className="flex-1">{i.label}</span>
                    <span className="font-mono text-xs">{i.carbs} {t("foodai.carbs")}{i.peak != null && ` · ${t("foodai.peak")} ${i.peak}`}</span>
                  </li>
                ))}
              </ul>
            )}
            <table className="w-full text-xs">
              <thead className="text-slate-500"><tr><th className="text-left">{/* date */}</th><th>{t("foodai.carbs")}</th><th>{t("foodai.spikes")}</th><th>{t("foodai.late")}</th></tr></thead>
              <tbody className="font-mono">
                {f.diary.map((d) => (
                  <tr key={d.date}><td>{d.date.slice(5)}</td><td className="text-center">{d.total_carbs}</td><td className="text-center">{d.spikes_after_meals}/{d.meals}</td><td className="text-center">{d.late_meals}</td></tr>
                ))}
              </tbody>
            </table>
          </section>
          <p className="text-xs text-slate-500">{f.method}</p>
        </div>
      )}
    </Panel>
  );
}
