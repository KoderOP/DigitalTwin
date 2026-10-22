import { Bar, BarChart, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Detail } from "../types";
import { COLORS, SLEEP_STAGE, fmtTime, ms } from "../lib/format";
import { hourTicks, type TimeDomain } from "./CgmChart";

// hypnogram ordering: Awake on top, Deep at the bottom (clinical convention)
const HYPNO_Y = [3, 2, 0, 1]; // stage index -> y (awake=3, light=2, deep=0, rem=1)
const HYPNO_LABEL: Record<number, string> = { 3: "Awake", 2: "Light", 1: "REM", 0: "Deep" };

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-0.5 text-[11px] font-medium text-slate-500 dark:text-slate-400">{label}</p>
      {children}
    </div>
  );
}

export function SignalsPanel({ d, dom }: { d: Detail; dom: TimeDomain }) {
  const s = d.series.filter((x) => ms(x.ts) >= dom.start).map((x) => ({
    t: ms(x.ts), hr: x.hr, hrv: x.hrv_rmssd, steps: x.steps, stage: x.sleep_stage == null ? null : HYPNO_Y[x.sleep_stage],
  }));
  const ticks = hourTicks(dom);
  const xAxis = (show: boolean) => (
    <XAxis dataKey="t" type="number" domain={[dom.start, dom.end]} ticks={ticks} tickFormatter={fmtTime} fontSize={10} hide={!show} allowDataOverflow />
  );
  const margin = { top: 2, right: 12, bottom: 0, left: -12 };
  return (
    <div className="space-y-1">
      <Row label={`Sleep stages${d.last_sleep_h != null ? ` · last night ${d.last_sleep_h} h` : ""}`}>
        <div className="h-20" role="img" aria-label="Sleep stage timeline">
          <ResponsiveContainer>
            <LineChart data={s} margin={margin}>
              {xAxis(false)}
              <YAxis domain={[-0.3, 3.3]} ticks={[0, 1, 2, 3]} tickFormatter={(v) => HYPNO_LABEL[v]} fontSize={9} width={52} interval={0} />
              <ReferenceLine x={dom.now} stroke={COLORS.grey} />
              <Tooltip labelFormatter={(t) => fmtTime(t as number)} formatter={(v: number) => [HYPNO_LABEL[v] ?? SLEEP_STAGE[0], "stage"]} contentStyle={{ fontSize: 12 }} />
              <Line type="stepAfter" dataKey="stage" stroke="#6A5ACD" dot={false} strokeWidth={1.5} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Row>
      <Row label="Heart rate (bpm, solid) · HRV RMSSD (ms, dashed)">
        <div className="h-24" role="img" aria-label="Heart rate and heart-rate variability">
          <ResponsiveContainer>
            <LineChart data={s} margin={margin}>
              {xAxis(false)}
              <YAxis yAxisId="hr" domain={["dataMin - 5", "dataMax + 5"]} fontSize={9} width={52} />
              <YAxis yAxisId="hrv" orientation="right" hide domain={[0, "dataMax + 10"]} />
              <ReferenceLine x={dom.now} yAxisId="hr" stroke={COLORS.grey} />
              <Tooltip labelFormatter={(t) => fmtTime(t as number)} contentStyle={{ fontSize: 12 }} />
              <Line yAxisId="hr" dataKey="hr" name="HR" stroke={COLORS.red} dot={false} strokeWidth={1.2} isAnimationActive={false} connectNulls={false} />
              <Line yAxisId="hrv" dataKey="hrv" name="HRV" stroke={COLORS.green} strokeDasharray="4 2" dot={false} strokeWidth={1.2} isAnimationActive={false} connectNulls={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Row>
      <Row label="Steps per 5 min">
        <div className="h-20" role="img" aria-label="Step count">
          <ResponsiveContainer>
            <BarChart data={s} margin={margin} barCategoryGap={0}>
              {xAxis(true)}
              <YAxis fontSize={9} width={52} />
              <ReferenceLine x={dom.now} stroke={COLORS.grey} />
              <Tooltip labelFormatter={(t) => fmtTime(t as number)} contentStyle={{ fontSize: 12 }} />
              <Bar dataKey="steps" fill={COLORS.sky} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Row>
    </div>
  );
}
