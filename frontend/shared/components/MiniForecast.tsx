import { Area, ComposedChart, Line, ReferenceArea, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { COLORS } from "../lib/format";

export interface MiniPoint { t: number; g?: number | null; band?: [number, number] | null; mid?: number | null; after?: number | null }

/**
 * Simplified glucose chart for patients: target zone shading, recent readings, and an estimate band.
 * Optionally a second line ("after") for before/after what-if comparisons.
 */
export function MiniForecast({ data, low, high, nowT, label, height = 160 }: {
  data: MiniPoint[]; low: number; high: number; nowT?: number; label: string; height?: number;
}) {
  const vals = data.flatMap((d) => [d.g, d.mid, d.after, ...(d.band ?? [])]).filter((v): v is number => typeof v === "number");
  const yMax = Math.max(high + 40, ...vals) + 10;
  const yMin = Math.min(low - 20, ...vals) - 5;
  return (
    <div style={{ height }} className="w-full" role="img" aria-label={label}>
      <ResponsiveContainer>
        <ComposedChart data={data} margin={{ top: 6, right: 6, bottom: 0, left: -24 }}>
          <ReferenceArea y1={low} y2={high} fill={COLORS.green} fillOpacity={0.12} ifOverflow="hidden" />
          <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} tick={false} axisLine={false} />
          <YAxis domain={[Math.floor(yMin), Math.ceil(yMax)]} ticks={[low, high]} fontSize={11} />
          {nowT && <ReferenceLine x={nowT} stroke={COLORS.grey} strokeDasharray="3 3" />}
          <Area dataKey="band" stroke="none" fill={COLORS.blue} fillOpacity={0.2} isAnimationActive={false} connectNulls />
          <Line dataKey="g" stroke="currentColor" strokeWidth={3} dot={false} isAnimationActive={false} connectNulls={false} />
          <Line dataKey="mid" stroke={COLORS.blue} strokeWidth={3} strokeDasharray="6 4" dot={false} isAnimationActive={false} connectNulls />
          <Line dataKey="after" stroke={COLORS.green} strokeWidth={3} dot={false} isAnimationActive={false} connectNulls />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
