import { ShieldCheck, Wifi, WifiOff } from "lucide-react";
import type { Detail } from "../types";
import { num } from "@shared/lib/format";

function Chip({ children }: { children: React.ReactNode }) {
  return <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-700 dark:bg-slate-800 dark:text-slate-300">{children}</span>;
}

export function PatientHeader({ d }: { d: Detail }) {
  const h = d.header;
  const dq = d.data_quality;
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <div className="flex flex-wrap items-baseline gap-2">
          <h1 className="font-mono text-xl font-bold text-slate-900 dark:text-white">{h.patient_id}</h1>
          <span className="text-sm text-slate-600 dark:text-slate-300">
            {h.age} y · {h.sex === "M" ? "Male" : "Female"} · {h.region} · T2D {num(h.years_since_dx, 1)} y{h.early_onset && " (early onset)"}
          </span>
        </div>
        <div className="mt-1 flex flex-wrap gap-1">
          <Chip>HbA1c <b>{h.hba1c.toFixed(1)}%</b></Chip>
          <Chip>FPG {num(h.fasting_glucose)} mg/dL</Chip>
          <Chip>BMI {h.bmi.toFixed(1)} ({h.bmi_band_sa}, SA cut-offs)</Chip>
          <Chip>Waist {num(h.waist_cm)} cm</Chip>
          <Chip>eGFR {num(h.egfr)}</Chip>
          <Chip>LDL {num(h.ldl)} · TG {num(h.triglycerides)}</Chip>
          <Chip>{h.diet.replace("_", "-")} · {h.staple}</Chip>
          <Chip>PRS z {h.prs > 0 ? "+" : ""}{h.prs.toFixed(1)}</Chip>
        </div>
        <div className="mt-1 flex flex-wrap gap-1 text-[11px]">
          <span className="text-slate-500">Medications:</span>
          {h.medications.length ? h.medications.map((m) => <Chip key={m}>{m}</Chip>) : <Chip>none</Chip>}
          <span className="ml-2 text-slate-500">Comorbidities:</span>
          {h.comorbidities.length ? h.comorbidities.map((m) => <Chip key={m}>{m}</Chip>) : <Chip>none recorded</Chip>}
        </div>
      </div>
      <div className="space-y-1 text-right text-[11px] text-slate-600 dark:text-slate-400">
        <p className="flex items-center justify-end gap-1" title={d.consent?.note}>
          <ShieldCheck className="h-3 w-3 text-risk-green" aria-hidden /> Consent: {d.consent?.status ?? "unknown"} (simulated)
        </p>
        <p className="flex items-center justify-end gap-1">
          {dq.status === "good" ? <Wifi className="h-3 w-3" aria-hidden /> : <WifiOff className="h-3 w-3 text-risk-amber" aria-hidden />}
          Data quality: <b>{dq.status}</b> · CGM 1 h {Math.round(dq.cgm_coverage_1h * 100)}% · watch {Math.round(dq.wearable_coverage_1h * 100)}%
        </p>
        {dq.imputing && <p className="text-amber-700 dark:text-amber-300">CGM gap {dq.minutes_since_cgm} min: last value carried forward (imputed)</p>}
        <p>Twin calibration: SI x{d.simulator.si_mult} · Gb x{d.simulator.gb_mult} · RMSE {num(d.simulator.calibration_rmse, 1)} mg/dL</p>
      </div>
    </div>
  );
}
