import { Clock, Moon, TrendingDown } from "lucide-react";
import { Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Detail, Prediction } from "../types";
import { COLORS, LEVEL_META, countdownText, fmtTime, ms, pct } from "@shared/lib/format";
import { LevelBadge } from "@shared/components/LevelBadge";
import { hourTicks, type TimeDomain } from "./CgmChart";

function arc(cx: number, cy: number, r: number, a0: number, a1: number) {
  const p = (a: number) => [cx + r * Math.cos(Math.PI * (1 - a)), cy - r * Math.sin(Math.PI * (1 - a))];
  const [x0, y0] = p(a0);
  const [x1, y1] = p(a1);
  return `M ${x0} ${y0} A ${r} ${r} 0 0 1 ${x1} ${y1}`;
}

/** Semicircular gauge of the calibrated spike probability with AMBER/RED threshold zones. */
export function RiskGauge({ p }: { p: Prediction }) {
  const { amber, red } = p.thresholds;
  const v = Math.max(0, Math.min(1, p.risk));
  const meta = LEVEL_META[p.level];
  const needle = Math.PI * (1 - v);
  return (
    <div className="flex flex-col items-center">
      <svg viewBox="0 0 200 118" className="w-full max-w-[230px]" role="img" aria-label={`Spike risk ${pct(v)}; level ${meta.label}`}>
        <path d={arc(100, 100, 80, 0, amber)} stroke={COLORS.green} strokeWidth={16} fill="none" />
        <path d={arc(100, 100, 80, amber, red)} stroke={COLORS.amber} strokeWidth={16} fill="none" />
        <path d={arc(100, 100, 80, red, 1)} stroke={COLORS.red} strokeWidth={16} fill="none" />
        <line x1={100} y1={100} x2={100 + 70 * Math.cos(needle)} y2={100 - 70 * Math.sin(needle)} stroke="currentColor" strokeWidth={3} className="text-slate-800 dark:text-slate-100" />
        <circle cx={100} cy={100} r={5} className="fill-slate-800 dark:fill-slate-100" />
        <text x={100} y={82} textAnchor="middle" className="fill-slate-900 text-[22px] font-bold dark:fill-white">{pct(v)}</text>
      </svg>
      <LevelBadge level={p.level} size="lg" />
      <p className="mt-2 flex items-center gap-1 text-sm font-medium text-slate-800 dark:text-slate-100">
        <Clock aria-hidden className="h-4 w-4" /> {countdownText(p.minutes_to_spike, p.level)}
      </p>
      {p.minutes_to_spike_basis && <p className="text-[11px] text-slate-500">(from the {p.minutes_to_spike_basis})</p>}
      <dl className="mt-2 grid w-full grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-slate-600 dark:text-slate-400">
        <dt>P(spike ≤ 120 min)</dt><dd className="text-right font-mono">{pct(p.risk, 1)}</dd>
        <dt>Thresholds</dt><dd className="text-right font-mono">A {pct(amber)} · R {pct(red)}</dd>
        {p.hypo_risk != null && (<><dt className="flex items-center gap-1"><TrendingDown className="h-3 w-3" aria-hidden />Hypo risk (advisory)</dt><dd className="text-right font-mono">{pct(p.hypo_risk, 1)}</dd></>)}
        <dt>Model</dt><dd className="text-right font-mono">{p.model}</dd>
      </dl>
      {p.nocturnal_flag && (
        <p className="mt-2 flex items-center gap-1 rounded bg-indigo-100 px-2 py-1 text-xs text-indigo-900 dark:bg-indigo-900/50 dark:text-indigo-100">
          <Moon aria-hidden className="h-3 w-3" /> {p.nocturnal_flag}
        </p>
      )}
    </div>
  );
}

/** Calibrated risk over time with threshold bands, so it is clear when the twin first raised an alert. */
export function RiskHistory({ d, dom }: { d: Detail; dom: TimeDomain }) {
  const p = d.prediction;
  if (!p) return null;
  const data = d.prediction_history.map((h) => ({ t: ms(h.ts), risk: h.risk }));
  return (
    <div className="h-28 w-full" role="img" aria-label="Spike risk over the last 12 hours">
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 4, right: 12, bottom: 0, left: -12 }}>
          <ReferenceArea y1={p.thresholds.amber} y2={p.thresholds.red} fill={COLORS.amber} fillOpacity={0.12} />
          <ReferenceArea y1={p.thresholds.red} y2={1} fill={COLORS.red} fillOpacity={0.12} />
          <XAxis dataKey="t" type="number" domain={[dom.start, dom.end]} ticks={hourTicks(dom)} tickFormatter={fmtTime} fontSize={10} allowDataOverflow />
          <YAxis domain={[0, 1]} ticks={[0, 0.5, 1]} tickFormatter={(v) => `${v * 100}%`} fontSize={10} />
          <ReferenceLine x={dom.now} stroke={COLORS.grey} />
          <Tooltip labelFormatter={(t) => fmtTime(t as number)} formatter={(v: number) => [pct(v, 1), "risk"]} contentStyle={{ fontSize: 12 }} />
          <Line dataKey="risk" stroke={COLORS.blue} dot={false} strokeWidth={1.6} isAnimationActive={false} connectNulls={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
