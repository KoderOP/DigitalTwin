import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { CheckCircle2, ClipboardList, MessageCircle, ShieldAlert } from "lucide-react";
import { AlertCard } from "@shared/components/AlertCard";
import { papi } from "../api";
import type { PatientView } from "../types";
import { BigButton, Panel, time } from "./ui";

/** Prioritised alerts (safety first), care-plan cards the patient can mark done, and doctor messages. */
export function Care({ v, token, readOnly, onChanged }: { v: PatientView; token: string; readOnly: boolean; onChanged: () => void }) {
  const { t } = useTranslation();
  useEffect(() => {
    if (readOnly) return;
    // seen-receipts for the doctor's engagement panel
    v.alerts.filter((a) => !a.seen).forEach((a) => void papi.ack(token, a.id, null));
    v.messages.filter((m) => !m.read_at && m.sender === "doctor").forEach((m) => void papi.msgRead(token, m.id));
  }, [v.alerts, v.messages, token, readOnly]);
  const labels = { understood: t("care.understood"), yes: t("common.yes"), no: t("common.no"), firstAid: t("care.first_aid"), call: t("care.call"), confidence: t("home.confidence") };
  const open = v.cards.filter((c) => c.status !== "done");
  const done = v.cards.filter((c) => c.status === "done");
  return (
    <div className="space-y-4">
      <Panel title={t("care.alerts")} right={<span className="flex items-center gap-1 text-xs text-slate-500"><ShieldAlert aria-hidden className="h-4 w-4" />{t("care.safety_on")}</span>}>
        {v.alerts.length === 0 ? <p>{t("care.no_alerts")}</p> : (
          <div className="space-y-3">
            {v.alerts.map((a) => (
              <AlertCard key={a.id} a={a} labels={labels} readOnly={readOnly}
                onUnderstood={(u) => papi.ack(token, a.id, u).then(onChanged)} />
            ))}
          </div>
        )}
      </Panel>
      <Panel title={<span className="flex items-center gap-2"><ClipboardList aria-hidden className="h-5 w-5" />{t("care.plan")}</span>}>
        <ul className="space-y-3">
          {open.map((c) => (
            <li key={c.id} className="rounded-xl border-2 border-slate-200 p-3 dark:border-slate-700">
              <p className="text-base font-semibold">{c.title}</p>
              {c.body && <p className="text-sm">{c.body}</p>}
              {!readOnly && <div className="mt-2"><BigButton variant="secondary" onClick={() => papi.cardDone(token, c.id).then(onChanged)}>
                <CheckCircle2 aria-hidden className="h-5 w-5" /> {t("care.mark_done")}</BigButton></div>}
            </li>
          ))}
          {done.map((c) => (
            <li key={c.id} className="flex items-center gap-2 text-slate-500"><CheckCircle2 aria-hidden className="h-5 w-5 text-risk-green" /><s>{c.title}</s> <span className="sr-only">{t("care.done")}</span></li>
          ))}
        </ul>
        <p className="mt-3 text-sm text-slate-500">{v.care_plan.med_note}</p>
      </Panel>
      <Panel title={<span className="flex items-center gap-2"><MessageCircle aria-hidden className="h-5 w-5" />{t("care.messages")}</span>}>
        <ul className="space-y-2">
          {v.messages.map((m) => (
            <li key={m.id} className="rounded-xl bg-sky-50 p-3 dark:bg-slate-800">
              <p className="text-xs text-slate-500">{m.author} · {time(m.ts_sim)}</p>
              <p className="text-base">{m.body}</p>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}
