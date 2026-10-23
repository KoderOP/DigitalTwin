import { Area, CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceDot, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import type { Detail } from "../types";
import { COLORS, fmtTime, ms } from "@shared/lib/format";

export interface TimeDomain { start: number; now: number; end: number }

export function timeDomain(d: Detail): TimeDomain {
  const now = d.series.length ? ms(d.series[d.series.length - 1].ts) : Date.now();
  return { start: now - 12 * 3600e3, now, end: now + 2 * 3600e3 };
}

export const hourTicks = (dom: TimeDomain) => {
  const out: number[] = [];
  const first = Math.ceil(dom.start / 3600e3) * 3600e3;
  for (let t = first; t <= dom.end; t += 2 * 3600e3) out.push(t);
  return out;
};

/** Live CGM: past 12 h, 2-h forecast with P10-P90 band, target range, alert & event markers. */
export function CgmChart({ d, dom }: { d: Detail; dom: TimeDomain }) {
  const p = d.prediction;
  const past = d.series.filter((s) => ms(s.ts) >= dom.start).map((s) => ({ t: ms(s.ts), cgm: s.cgm }));
  const g0 = p?.g_now ?? past.at(-1)?.cgm ?? null;
  const fc = p
    ? [{ t: dom.now, p50: g0, band: [g0, g0] as [number | null, number | null] },
       ...p.forecast.map((f) => ({ t: dom.now + f.minutes * 60e3, p50: f.p50, band: [f.p10, f.p90] as [number, number] }))]
    : [];
  const data = [...past, ...fc];
  const meals = d.events.filter((e) => e.type === "meal" && ms(e.ts) >= dom.start).map((e) => ({ t: ms(e.ts), y: 52, label: `${e.label} (${e.amount ?? "?"} g)` }));
  const meds = d.events.filter((e) => e.type === "med" && ms(e.ts) >= dom.start).map((e) => ({ t: ms(e.ts), y: 44, label: e.label }));
  const alerts = d.alerts.filter((a) => ms(a.ts) >= dom.start);
  const yMax = Math.max(300, ...past.map((x) => x.cgm ?? 0), ...(p?.forecast.map((f) => f.p90) ?? [0])) + 10;

  return (
    <div className="h-72 w-full" role="img" aria-label="Continuous glucose chart with 2-hour forecast">
      <ResponsiveContainer>
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-slate-200 dark:text-slate-800" />
          <ReferenceArea y1={70} y2={180} fill={COLORS.green} fillOpacity={0.08} ifOverflow="hidden" />
          <ReferenceArea x1={dom.now} x2={dom.end} fill={COLORS.sky} fillOpacity={0.06} ifOverflow="hidden" />
          <XAxis dataKey="t" type="number" domain={[dom.start, dom.end]} ticks={hourTicks(dom)} tickFormatter={fmtTime} fontSize={11} allowDataOverflow />
          <YAxis domain={[40, yMax]} fontSize={11} unit="" ticks={[70, 180, 250, 300]} />
          <Tooltip
            labelFormatter={(t) => fmtTime(t as number)}
            formatter={(v: unknown, name: string) => (Array.isArray(v) ? [`${v[0]}–${v[1]} mg/dL`, "P10–P90"] : [`${v} mg/dL`, name])}
            contentStyle={{ fontSize: 12 }}
          />
          <ReferenceLine y={180} stroke={COLORS.red} strokeDasharray="5 4" label={{ value: "180", position: "insideTopLeft", fontSize: 10, fill: COLORS.red }} />
          <ReferenceLine y={70} stroke={COLORS.amber} strokeDasharray="5 4" label={{ value: "70", position: "insideBottomLeft", fontSize: 10, fill: COLORS.amber }} />
          <ReferenceLine x={dom.now} stroke={COLORS.grey} label={{ value: "now", position: "top", fontSize: 10 }} />
          <Area dataKey="band" stroke="none" fill={COLORS.blue} fillOpacity={0.18} name="Forecast P10–P90" isAnimationActive={false} connectNulls />
          <Line dataKey="cgm" stroke="currentColor" className="text-slate-800 dark:text-slate-100" dot={false} strokeWidth={1.6} name="CGM" isAnimationActive={false} connectNulls={false} />
          <Line dataKey="p50" stroke={COLORS.blue} strokeDasharray="6 3" dot={{ r: 2 }} strokeWidth={2} name="Forecast P50" isAnimationActive={false} connectNulls />
          <Scatter data={meals} dataKey="y" fill={COLORS.amber} shape="triangle" name="Meal (logged)" isAnimationActive={false} />
          <Scatter data={meds} dataKey="y" fill={COLORS.blue} shape="diamond" name="Medication (logged)" isAnimationActive={false} />
          {alerts.map((a) => (
            <ReferenceDot key={a.id} x={ms(a.ts)} y={a.g_at_alert} r={6} fill={a.level === "RED" ? COLORS.red : COLORS.amber} stroke="white"
              label={{ value: a.level === "RED" ? "!!" : "!", position: "top", fontSize: 11, fontWeight: 700 }} ifOverflow="extendDomain" />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
