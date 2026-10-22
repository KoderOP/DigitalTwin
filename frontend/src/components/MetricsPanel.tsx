import { Area, ComposedChart, Line, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Detail, Metrics } from "../types";
import { COLORS, num } from "../lib/format";

const SEGMENTS: { key: keyof Metrics | "tir_only" | "tbr_only" | "tar_only"; label: string; color: string }[] = [
  { key: "tar250", label: ">250", color: "#A6461A" },
  { key: "tar_only", label: "181–250", color: COLORS.amber },
  { key: "tir", label: "70–180", color: COLORS.green },
  { key: "tbr_only", label: "54–69", color: COLORS.sky },
  { key: "tbr54", label: "<54", color: COLORS.blue },
];

export function TirBar({ m, label }: { m: Metrics; label: string }) {
  const vals: Record<string, number> = {
    tar250: m.tar250, tar_only: Math.max(m.tar - m.tar250, 0), tir: m.tir, tbr_only: Math.max(m.tbr - m.tbr54, 0), tbr54: m.tbr54,
  };
  return (
    <div>
      <p className="mb-1 text-[11px] font-medium text-slate-500">{label}</p>
      <div className="flex h-5 w-full overflow-hidden rounded" role="img" aria-label={`Time in range ${m.tir}%, above ${m.tar}%, below ${m.tbr}%`}>
        {SEGMENTS.map((s) => (vals[s.key] > 0 ? <div key={s.key} title={`${s.label}: ${vals[s.key].toFixed(1)}%`} style={{ width: `${vals[s.key]}%`, backgroundColor: s.color }} /> : null))}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 text-[10px] text-slate-600 dark:text-slate-400">
        {SEGMENTS.map((s) => (
          <span key={s.key} className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: s.color }} aria-hidden />
            {s.label} {num(vals[s.key], 1)}%
          </span>
        ))}
      </div>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg bg-slate-50 p-2 dark:bg-slate-800/60" title={hint}>
      <p className="text-[10px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className="font-mono text-lg font-semibold text-slate-900 dark:text-slate-50">{value}</p>
    </div>
  );
}

export function MetricsPanel({ d }: { d: Detail }) {
  const m = d.metrics_24h;
  const m14 = d.metrics_14d;
  const agp = d.agp.map((a) => ({ h: a.minute / 60, outer: [a.p5, a.p95], inner: [a.p25, a.p75], p50: a.p50 }));
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-4 gap-2">
        <Stat label="Mean 24 h" value={`${num(m.mean)}`} hint="mg/dL" />
        <Stat label="CV 24 h" value={`${num(m.cv, 1)}%`} hint="Glycemic variability; target ≤ 36%" />
        <Stat label="GMI 14 d" value={`${num(m14.gmi, 1)}%`} hint="Glucose Management Indicator" />
        <Stat label="TIR 14 d" value={`${num(m14.tir)}%`} hint="Target > 70%" />
      </div>
      <TirBar m={m} label="Time in ranges, last 24 h" />
      <TirBar m={m14} label="Time in ranges, last 14 days" />
      <div>
        <p className="mb-1 text-[11px] font-medium text-slate-500">Ambulatory Glucose Profile, 14 days (median, IQR, 5–95%)</p>
        <div className="h-40" role="img" aria-label="Ambulatory glucose profile">
          <ResponsiveContainer>
            <ComposedChart data={agp} margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
              <ReferenceArea y1={70} y2={180} fill={COLORS.green} fillOpacity={0.08} />
              <XAxis dataKey="h" type="number" domain={[0, 24]} ticks={[0, 4, 8, 12, 16, 20, 24]} tickFormatter={(h) => `${String(h).padStart(2, "0")}:00`} fontSize={10} />
              <YAxis domain={[40, "dataMax + 20"]} fontSize={10} />
              <Tooltip formatter={(v: unknown) => (Array.isArray(v) ? `${v[0]}–${v[1]}` : `${v}`)} labelFormatter={(h) => `${Math.floor(h as number)}:${String(((h as number) % 1) * 60).padStart(2, "0")}`} contentStyle={{ fontSize: 12 }} />
              <Area dataKey="outer" stroke="none" fill={COLORS.sky} fillOpacity={0.25} name="5–95%" isAnimationActive={false} />
              <Area dataKey="inner" stroke="none" fill={COLORS.blue} fillOpacity={0.35} name="25–75%" isAnimationActive={false} />
              <Line dataKey="p50" stroke={COLORS.blue} dot={false} strokeWidth={2} name="median" isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>
      <div>
        <p className="mb-1 text-[11px] font-medium text-slate-500">Daily summary</p>
        <table className="w-full text-[11px]">
          <thead className="text-slate-500"><tr><th className="text-left">Date</th><th>Mean</th><th>TIR</th><th>TAR</th><th>TBR</th><th>CV</th></tr></thead>
          <tbody className="font-mono text-slate-700 dark:text-slate-300">
            {d.daily.slice(-7).map((r) => (
              <tr key={r.date}><td>{r.date.slice(5)}</td><td className="text-center">{num(r.mean)}</td><td className="text-center">{num(r.tir)}%</td><td className="text-center">{num(r.tar)}%</td><td className="text-center">{num(r.tbr, 1)}%</td><td className="text-center">{num(r.cv)}%</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
