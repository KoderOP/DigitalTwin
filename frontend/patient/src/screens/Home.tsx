import { useTranslation } from "react-i18next";
import { ArrowDown, ArrowUp, Footprints, GlassWater, Pill, Star, Utensils, Candy, Stethoscope } from "lucide-react";
import { PatientLevelBadge } from "@shared/components/StatusBadges";
import { MiniForecast, type MiniPoint } from "@shared/components/MiniForecast";
import { AlertCard } from "@shared/components/AlertCard";
import type { PatientView } from "../types";
import { Panel, ReadAloud, time } from "./ui";

const ACTION_ICON = { walk: Footprints, plate: Utensils, candy: Candy, pill: Pill, water: GlassWater, star: Star } as const;

export function chartData(v: PatientView): { data: MiniPoint[]; nowT: number } {
  const nowT = new Date(v.glucose.ts ?? v.now).getTime();
  const past: MiniPoint[] = v.glucose.history.map((h) => ({ t: new Date(h.ts).getTime(), g: h.g }));
  const fc: MiniPoint[] = v.glucose.forecast.map((f) => ({ t: nowT + f.minutes * 60000, mid: f.mid, band: [f.low, f.high] }));
  return { data: [...past, ...fc], nowT };
}

export function Home({ v, onGo }: { v: PatientView; onGo: (tab: string) => void }) {
  const { t } = useTranslation();
  const s = v.status;
  const Icon = ACTION_ICON[v.next_action.icon as keyof typeof ACTION_ICON] ?? Star;
  const { data, nowT } = chartData(v);
  const sentence = `${s.sentence} ${v.next_action.text}`;
  return (
    <div className="space-y-4">
      {v.safety.low_now && v.safety.first_aid && (
        <AlertCard readOnly a={{ id: 0, ts: v.now, kind: "hypo_detected", priority: 0, safety: true, level: "LOW", title: v.safety.first_aid.title,
          body: s.sentence, confidence: null, seen: false, understood: null, disclaimer: v.disclaimer, first_aid: v.safety.first_aid }}
          labels={{ understood: "", yes: "", no: "", firstAid: t("care.first_aid"), call: t("care.call"), confidence: t("home.confidence") }} />
      )}
      <Panel>
        <div className="flex flex-col items-start gap-3">
          <PatientLevelBadge level={s.level} label={t(`levels.${s.level}`)} />
          <p className="text-2xl font-bold leading-snug" data-testid="status-sentence">{s.sentence}</p>
          {s.sub && <p className="text-base text-slate-600 dark:text-slate-300">{s.sub}</p>}
          <p className="text-sm text-slate-500">{t("home.confidence")}: {s.confidence.label}{s.confidence.pct != null && ` (${s.confidence.pct}%)`}</p>
          <ReadAloud text={sentence} />
        </div>
      </Panel>
      <Panel title={t("home.now")} right={<span className="text-sm text-slate-500">{v.glucose.ts && time(v.glucose.ts)}</span>}>
        <p className="flex items-baseline gap-2" aria-label={`${v.glucose.value ?? v.glucose.estimated} ${v.glucose.unit}, ${v.glucose.trend_text}`}>
          <span className="text-5xl font-bold">{v.glucose.value ?? (v.glucose.estimated != null ? `~${Math.round(v.glucose.estimated)}` : "–")}</span>
          <span className="text-lg">{v.glucose.unit}</span>
          <span className="text-4xl" aria-hidden>{v.glucose.trend_icon}</span>
          <span className="text-base">{v.glucose.trend_text}</span>
        </p>
        {!v.glucose.sensor_ok && <p className="mt-1 text-sm font-semibold text-amber-700 dark:text-amber-300">{t("home.sensor_gap")}</p>}
        <p className="mt-2 text-sm font-semibold">{t("home.next2h")} · {t("home.target", { low: v.target.low, high: v.target.high })}</p>
        <MiniForecast data={data} nowT={nowT} low={v.target.low} high={v.target.high} label={t("home.next2h")} />
      </Panel>
      <Panel title={t("home.next_action")}>
        <div className="flex items-center gap-3">
          <Icon aria-hidden className="h-10 w-10 shrink-0 text-brand" />
          <p className="text-xl font-semibold" data-testid="next-action">{v.next_action.text}</p>
        </div>
      </Panel>
      <Panel title={t("home.why")}>
        <WhyBlock v={v} />
      </Panel>
      <button onClick={() => onGo("care")} className="flex min-h-14 w-full items-center gap-3 rounded-2xl bg-white p-4 text-left shadow-sm dark:bg-slate-900">
        <Stethoscope aria-hidden className="h-8 w-8 text-brand" />
        <span className="text-lg font-semibold">{t("home.care_team", { doctor: v.doctor.title })}</span>
      </button>
      <p className="text-center text-xs text-slate-500">{v.disclaimer} {v.safety.note}</p>
    </div>
  );
}

export function WhyBlock({ v }: { v: PatientView }) {
  return (
    <div>
      <p className="text-lg" data-testid="why-sentence">{v.why.sentence}</p>
      <ul className="mt-2 space-y-1">
        {v.why.items.map((i) => (
          <li key={i.text} className="flex items-center gap-2 text-base">
            {i.direction === "up" ? <ArrowUp aria-label="raises" className="h-5 w-5 text-risk-red" /> : <ArrowDown aria-label="lowers" className="h-5 w-5 text-risk-green" />}
            {i.text}
          </li>
        ))}
      </ul>
    </div>
  );
}
