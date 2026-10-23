import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Award, Eye, Lock, Users } from "lucide-react";
import { papi } from "../api";
import type { PatientView } from "../types";
import { LangPicker } from "./Onboarding";
import { BigButton, Panel } from "./ui";

/** Progress (positive framing, no shaming) and the Privacy & Consent centre. */
export function Me({ v, token, readOnly, onWithdrawn }: { v: PatientView; token: string; readOnly: boolean; onWithdrawn: () => void }) {
  const { t } = useTranslation();
  const [log, setLog] = useState<{ ts: string; who: string; action: string }[]>([]);
  const [link, setLink] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  useEffect(() => { papi.accessLog(token).then(setLog).catch(() => undefined); }, [token]);
  const p = v.progress;
  return (
    <div className="space-y-4">
      {p && v.features.progress && (
        <Panel title={t("me.progress")}>
          <div className="grid grid-cols-3 gap-2 text-center">
            <div><p className="text-3xl font-bold">{p.today_tir}%</p><p className="text-sm">{t("me.today")}</p></div>
            <div><p className="text-3xl font-bold">{p.week_tir}%</p><p className="text-sm">{t("me.week")}</p></div>
            <div><p className="flex items-center justify-center gap-1 text-3xl font-bold"><Award aria-hidden className="h-6 w-6 text-amber-500" />{p.streak}</p><p className="text-sm">{t("me.streak")}</p></div>
          </div>
          <p className="mt-3 text-lg">{p.message}</p>
          <p className="text-sm text-slate-500">{p.week_text}</p>
          <ul className="mt-3 space-y-1" aria-label={t("me.week")}>
            {p.days.map((d) => (
              <li key={d.date} className="flex items-center gap-2 text-sm">
                <span className="w-12 font-mono">{d.date.slice(5)}</span>
                <span className="h-3 flex-1 rounded bg-slate-200 dark:bg-slate-700" aria-hidden>
                  <span className="block h-3 rounded bg-risk-green" style={{ width: `${d.tir}%` }} />
                </span>
                <span className="w-10 text-right font-mono">{d.tir}%</span>
              </li>
            ))}
          </ul>
        </Panel>
      )}
      <Panel title={<span className="flex items-center gap-2"><Lock aria-hidden className="h-5 w-5" />{t("me.privacy")}</span>}>
        <p className="rounded-xl bg-amber-100 p-2 text-sm font-semibold text-amber-950">{t("app.synthetic")}</p>
        <h3 className="mt-3 font-semibold">{t("me.shared")}</h3>
        <ul className="ml-5 list-disc text-base">
          <li>{t("me.shared_sensor")}</li><li>{t("me.shared_logs")}</li><li>{t("me.shared_doctor", { doctor: v.doctor.title })}</li>
        </ul>
        <h3 className="mt-3 font-semibold">{t("me.language")}</h3>
        <LangPicker onPick={(code) => { if (!readOnly) void papi.language(token, code); }} />
        <h3 className="mt-3 flex items-center gap-2 font-semibold"><Eye aria-hidden className="h-5 w-5" />{t("me.access_log")}</h3>
        <ul className="max-h-48 overflow-y-auto text-sm" data-testid="access-log">
          {log.map((r, i) => <li key={i} className="border-b border-slate-100 py-1 dark:border-slate-800"><span className="font-mono text-xs">{r.ts.slice(5, 16).replace("T", " ")}</span> · {r.who} · {r.action.replace(/_/g, " ")}</li>)}
        </ul>
        {v.features.caregiver && !readOnly && (
          <div className="mt-3">
            <h3 className="flex items-center gap-2 font-semibold"><Users aria-hidden className="h-5 w-5" />{t("me.caregiver")}</h3>
            {link ? <p className="break-all rounded bg-slate-100 p-2 text-xs dark:bg-slate-800">{link}</p> :
              <BigButton variant="secondary" onClick={() => papi.caregiverLink(token).then((r) => setLink(r.link)).catch((e) => setLink(String(e)))}>{t("me.caregiver_make")}</BigButton>}
          </div>
        )}
        {!readOnly && (
          <div className="mt-4">
            {!confirm ? <BigButton variant="danger" onClick={() => setConfirm(true)}>{t("me.withdraw")}</BigButton> : (
              <div className="space-y-2 rounded-xl border-2 border-red-700 p-3">
                <p className="text-base">{t("me.withdraw_confirm")}</p>
                <BigButton variant="danger" onClick={() => papi.withdraw(token).then(onWithdrawn)}>{t("common.yes")}</BigButton>
                <BigButton variant="secondary" onClick={() => setConfirm(false)}>{t("common.no")}</BigButton>
              </div>
            )}
          </div>
        )}
      </Panel>
    </div>
  );
}
