import { AlertOctagon, AlertTriangle, Bell, Info, Phone } from "lucide-react";
import { COLORS } from "../lib/format";

export interface PatientAlert {
  id: number;
  ts: string;
  kind: string;
  priority: number;
  safety: boolean;
  level: string;
  title: string;
  body: string;
  confidence: { pct: number; label: string } | null;
  seen: boolean;
  understood: number | null;
  disclaimer: string;
  first_aid: { title: string; steps: string[]; emergency: string; contact: string } | null;
}

const STYLE: Record<string, { color: string; Icon: typeof Bell }> = {
  RED: { color: COLORS.red, Icon: AlertOctagon },
  LOW: { color: "#b91c1c", Icon: AlertOctagon },
  AMBER: { color: COLORS.amber, Icon: AlertTriangle },
  INFO: { color: COLORS.blue, Icon: Info },
};

/**
 * Alert card shared by the patient app (and the doctor's preview). Every alert shows a confidence
 * level and the "not medical advice / synthetic demo" notice; low-glucose alerts add first-aid steps.
 */
export function AlertCard({ a, labels, onUnderstood, readOnly = false }: {
  a: PatientAlert;
  labels: { understood: string; yes: string; no: string; firstAid: string; call: string; confidence: string };
  onUnderstood?: (v: boolean) => void;
  readOnly?: boolean;
}) {
  const s = STYLE[a.level] ?? STYLE.INFO;
  return (
    <article className={`rounded-2xl border-2 p-4 ${a.seen ? "opacity-80" : ""}`} style={{ borderColor: s.color }} aria-live={a.safety ? "assertive" : "polite"}>
      <header className="flex items-start gap-2">
        <s.Icon aria-hidden className="mt-0.5 h-6 w-6 shrink-0" style={{ color: s.color }} />
        <div className="flex-1">
          <h3 className="text-base font-bold">{a.title}</h3>
          <p className="text-base">{a.body}</p>
          <p className="mt-1 text-xs text-slate-500">
            {new Date(a.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            {a.confidence && ` · ${labels.confidence}: ${a.confidence.label} (${a.confidence.pct}%)`}
          </p>
        </div>
      </header>
      {a.first_aid && (
        <div className="mt-3 rounded-xl bg-red-50 p-3 text-sm text-red-950 dark:bg-red-950/40 dark:text-red-100">
          <p className="font-bold">{labels.firstAid}</p>
          <ol className="ml-4 list-decimal space-y-1">{a.first_aid.steps.map((st) => <li key={st}>{st}</li>)}</ol>
          <p className="mt-2 font-semibold">{a.first_aid.emergency}</p>
          <a href="tel:108" className="mt-2 inline-flex min-h-12 items-center gap-2 rounded-xl bg-red-700 px-4 py-2 font-bold text-white">
            <Phone aria-hidden className="h-5 w-5" /> {labels.call}
          </a>
          <p className="mt-1">{a.first_aid.contact}</p>
        </div>
      )}
      <p className="mt-2 text-[11px] text-slate-500">{a.disclaimer}</p>
      {!readOnly && onUnderstood && a.understood === null && (
        <div className="mt-2 flex items-center gap-2 text-sm">
          <span>{labels.understood}</span>
          <button className="min-h-11 rounded-lg border px-4" onClick={() => onUnderstood(true)}>{labels.yes}</button>
          <button className="min-h-11 rounded-lg border px-4" onClick={() => onUnderstood(false)}>{labels.no}</button>
        </div>
      )}
    </article>
  );
}
