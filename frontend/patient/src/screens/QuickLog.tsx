import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { CheckCircle2, Footprints, Pill, XCircle } from "lucide-react";
import { AlertCard } from "@shared/components/AlertCard";
import { papi } from "../api";
import { BigButton, Panel } from "./ui";

const FOODS = [
  { id: "idli_sambar", emoji: "🍘" }, { id: "dal_chawal", emoji: "🍛" }, { id: "roti_sabzi", emoji: "🫓" },
  { id: "poha", emoji: "🥣" }, { id: "biryani", emoji: "🍚" },
] as const;
const SYMPTOMS = ["dizziness", "thirst", "fatigue", "sweating"] as const;
type FirstAid = { title: string; steps: string[]; emergency: string; contact: string };

/**
 * One-tap logging. Time-to-log is measured from the first tap to saving (in-app usability metric).
 * In the simulator a log also makes the virtual patient do it, so the next prediction reflects it.
 */
export function QuickLog({ token, onLogged }: { token: string; onLogged?: () => void }) {
  const { t } = useTranslation();
  const [food, setFood] = useState<string | null>(null);
  const [portion, setPortion] = useState<"small" | "regular" | "large">("regular");
  const [syms, setSyms] = useState<string[]>([]);
  const [toast, setToast] = useState<string | null>(null);
  const [firstAid, setFirstAid] = useState<FirstAid | null>(null);
  const started = useRef<number | null>(null);
  const touch = () => { if (started.current === null) started.current = performance.now(); };

  const save = async (body: Record<string, unknown>) => {
    const duration_ms = started.current === null ? 0 : Math.round(performance.now() - started.current);
    const r = await papi.log(token, { ...body, duration_ms });
    started.current = null;
    setToast(t("log.saved"));
    if (r.safety) setFirstAid(r.safety.first_aid);
    setFood(null);
    setSyms([]);
    onLogged?.();
    setTimeout(() => setToast(null), 4000);
  };

  return (
    <div className="space-y-4">
      {toast && <p role="status" className="rounded-xl bg-green-100 p-3 text-center text-lg font-semibold text-green-900">{toast}</p>}
      {firstAid && (
        <AlertCard readOnly a={{ id: 0, ts: new Date().toISOString(), kind: "hypo_detected", priority: 0, safety: true, level: "LOW", title: firstAid.title,
          body: "", confidence: null, seen: false, understood: null, disclaimer: t("app.not_advice"), first_aid: firstAid }}
          labels={{ understood: "", yes: "", no: "", firstAid: t("care.first_aid"), call: t("care.call"), confidence: "" }} />
      )}
      <Panel title={t("log.meal")}>
        <div className="grid grid-cols-3 gap-2">
          {FOODS.map((f) => (
            <button key={f.id} aria-pressed={food === f.id} onClick={() => { touch(); setFood(f.id); }}
              className={`flex min-h-20 flex-col items-center justify-center rounded-2xl border-2 p-2 text-sm font-semibold ${food === f.id ? "border-brand bg-sky-50 dark:bg-slate-800" : "border-slate-200 dark:border-slate-700"}`}>
              <span className="text-3xl" aria-hidden>{f.emoji}</span>{t(`food.${f.id}`)}
            </button>
          ))}
        </div>
        {food && (
          <div className="mt-3 space-y-3">
            <p className="font-semibold">{t("log.portion")}</p>
            <div className="grid grid-cols-3 gap-2" role="group" aria-label={t("log.portion")}>
              {(["small", "regular", "large"] as const).map((p) => (
                <button key={p} aria-pressed={portion === p} onClick={() => setPortion(p)}
                  className={`min-h-12 rounded-xl border-2 font-semibold ${portion === p ? "border-brand bg-brand text-white" : "border-slate-300"}`}>{t(`log.${p}`)}</button>
              ))}
            </div>
            <BigButton onClick={() => save({ kind: "meal", food, portion })}>{t("common.save")}</BigButton>
          </div>
        )}
      </Panel>
      <Panel title={t("log.walk")}>
        <div className="grid grid-cols-2 gap-2">
          {[15, 30].map((m) => (
            <BigButton key={m} variant="secondary" onClick={() => { touch(); void save({ kind: "exercise", minutes: m }); }}>
              <Footprints aria-hidden className="h-6 w-6" /> {t(m === 15 ? "log.walk15" : "log.walk30")}
            </BigButton>
          ))}
        </div>
      </Panel>
      <Panel title={t("log.med")}>
        <div className="grid grid-cols-2 gap-2">
          <BigButton variant="secondary" onClick={() => { touch(); void save({ kind: "med", status: "taken" }); }}><CheckCircle2 aria-hidden className="h-6 w-6 text-risk-green" /><Pill aria-hidden className="h-5 w-5" />{t("log.taken")}</BigButton>
          <BigButton variant="secondary" onClick={() => { touch(); void save({ kind: "med", status: "missed" }); }}><XCircle aria-hidden className="h-6 w-6 text-risk-red" /><Pill aria-hidden className="h-5 w-5" />{t("log.missed")}</BigButton>
        </div>
        <p className="mt-2 text-sm text-slate-500">{t("log.med_note")}</p>
      </Panel>
      <Panel title={t("log.symptoms")}>
        <div className="flex flex-wrap gap-2">
          {SYMPTOMS.map((s) => (
            <button key={s} aria-pressed={syms.includes(s)} onClick={() => { touch(); setSyms((x) => (x.includes(s) ? x.filter((y) => y !== s) : [...x, s])); }}
              className={`min-h-12 rounded-full border-2 px-4 text-base ${syms.includes(s) ? "border-brand bg-brand text-white" : "border-slate-300"}`}>{t(`symptoms.${s}`)}</button>
          ))}
        </div>
        {syms.length > 0 && <div className="mt-3"><BigButton onClick={() => save({ kind: "symptom", symptoms: syms })}>{t("common.save")}</BigButton></div>}
      </Panel>
    </div>
  );
}
