import { AlertOctagon, AlertTriangle, ArrowUpCircle, Ban, CheckCircle2, CircleDashed, Mail, PauseCircle, ShieldQuestion, Smile } from "lucide-react";
import type { PatientLevel, PortalState } from "../types";
import { COLORS } from "../lib/format";

const PORTAL: Record<PortalState, { label: string; color: string; Icon: typeof Mail }> = {
  NOT_ENROLLED: { label: "Not enrolled", color: "#6b7280", Icon: CircleDashed },
  INVITED: { label: "Invited", color: COLORS.blue, Icon: Mail },
  CONSENT_PENDING: { label: "Consent pending", color: "#7c3aed", Icon: ShieldQuestion },
  ACTIVE: { label: "Active", color: COLORS.green, Icon: CheckCircle2 },
  PAUSED: { label: "Paused", color: COLORS.amber, Icon: PauseCircle },
  REVOKED: { label: "Revoked", color: "#991b1b", Icon: Ban },
};

/** Patient-interface lifecycle badge (icon + text, never colour alone). */
export function PortalStatusBadge({ state }: { state: PortalState }) {
  const m = PORTAL[state];
  return (
    <span className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium" style={{ borderColor: m.color, color: m.color }}
      aria-label={`Patient app: ${m.label}`}>
      <m.Icon className="h-3 w-3" aria-hidden /> {m.label}
    </span>
  );
}

export const PATIENT_LEVEL: Record<PatientLevel, { color: string; Icon: typeof Smile; shape: string }> = {
  GREEN: { color: COLORS.green, Icon: Smile, shape: "rounded-full" },
  AMBER: { color: COLORS.amber, Icon: AlertTriangle, shape: "rounded-xl" },
  RED: { color: COLORS.red, Icon: AlertOctagon, shape: "rounded-md" },
  HIGH: { color: COLORS.high, Icon: ArrowUpCircle, shape: "rounded-md" },
  LOW: { color: "#b91c1c", Icon: AlertOctagon, shape: "rounded-md" },
};

/** Large glanceable status for the patient: icon + label text + colour. */
export function PatientLevelBadge({ level, label }: { level: PatientLevel; label: string }) {
  const m = PATIENT_LEVEL[level];
  return (
    <span role="status" aria-label={label} className={`inline-flex items-center gap-2 px-4 py-2 text-lg font-bold text-white ${m.shape}`}
      style={{ backgroundColor: m.color }}>
      <m.Icon aria-hidden className="h-6 w-6" /> {label}
    </span>
  );
}
