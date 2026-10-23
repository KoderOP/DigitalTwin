import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Bluetooth, Check, KeyRound, Languages, ShieldCheck, Watch } from "lucide-react";
import { LANGUAGES } from "@shared/i18n";
import { ApiError, papi } from "../api";
import type { Doctor, PendingView } from "../types";
import { BigButton, Screen } from "./ui";

/** Invite link -> welcome -> one-time PIN. On success the parent stores the patient session token. */
export function InviteFlow({ invite, onVerified }: { invite: string; onVerified: (token: string) => void }) {
  const { t, i18n } = useTranslation();
  const [doctor, setDoctor] = useState<{ name: string; title: string } | null>(null);
  const [dev, setDev] = useState(false);
  const [step, setStep] = useState<"welcome" | "otp">("welcome");
  const [otp, setOtp] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [demoMsg, setDemoMsg] = useState<string | null>(null);
  const opened = useRef(false);

  useEffect(() => {
    if (opened.current) return;
    opened.current = true;
    papi.open(invite)
      .then((r) => { setDoctor(r.doctor); setDev(r.dev_mode); void i18n.changeLanguage(r.language); })
      .catch((e: ApiError) => setErr(e.status === 410 || e.status === 401 ? t("state.invalid") : e.message));
  }, [invite, i18n, t]);

  if (err && !doctor) return <Screen><p role="alert" className="text-lg">{err}</p></Screen>;
  if (!doctor) return <Screen><p>{t("common.loading")}</p></Screen>;

  if (step === "welcome")
    return (
      <Screen>
        <LangPicker />
        <ShieldCheck aria-hidden className="mx-auto h-16 w-16 text-brand" />
        <h1 className="text-center text-3xl font-bold">{t("onboarding.welcome_title")}</h1>
        <p className="text-center text-lg">{t("onboarding.welcome_body", { doctor: doctor.name })}</p>
        <BigButton onClick={() => setStep("otp")}>{t("common.next")}</BigButton>
      </Screen>
    );

  const verify = async () => {
    setErr(null);
    try {
      const r = await papi.verify(invite, otp);
      onVerified(r.token);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  };
  return (
    <Screen>
      <KeyRound aria-hidden className="mx-auto h-14 w-14 text-brand" />
      <h1 className="text-center text-2xl font-bold">{t("onboarding.otp_title")}</h1>
      <p className="text-center">{t("onboarding.otp_body")}</p>
      <label className="block text-center">
        <span className="sr-only">{t("onboarding.otp_label")}</span>
        <input inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={otp} aria-label={t("onboarding.otp_label")}
          onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
          className="w-56 rounded-xl border-2 border-slate-300 bg-white p-3 text-center font-mono text-3xl tracking-[0.4em] dark:bg-slate-800" />
      </label>
      {err && <p role="alert" className="text-center font-semibold text-red-700 dark:text-red-300">{err}</p>}
      <BigButton disabled={otp.length !== 6} onClick={verify}>{t("onboarding.verify")}</BigButton>
      {dev && (
        <div className="text-center text-sm">
          <button className="underline" onClick={() => papi.devOtp(invite).then((r) => setDemoMsg(r.message))}>{t("onboarding.demo_code")}</button>
          {demoMsg && <p className="mt-2 rounded-lg bg-amber-100 p-2 text-amber-950" data-testid="demo-sms">{demoMsg}</p>}
        </div>
      )}
    </Screen>
  );
}

export function LangPicker({ onPick }: { onPick?: (code: string) => void }) {
  const { i18n } = useTranslation();
  return (
    <div className="flex justify-center gap-2" role="group" aria-label="Language">
      <Languages aria-hidden className="h-6 w-6 self-center" />
      {LANGUAGES.map((l) => (
        <button key={l.code} aria-pressed={i18n.language === l.code}
          onClick={() => { void i18n.changeLanguage(l.code); onPick?.(l.code); }}
          className={`min-h-11 rounded-full border-2 px-4 text-base ${i18n.language === l.code ? "border-brand bg-brand text-white" : "border-slate-300"}`}>
          {l.label}
        </button>
      ))}
    </div>
  );
}

/** Consent (notice, purpose, rights, choices) -> language -> short tour -> simulated wearable -> start. */
export function ConsentFlow({ view, onAccept }: { view: PendingView; onAccept: (language: string, choices: Record<string, boolean>) => Promise<void> }) {
  const { t, i18n } = useTranslation();
  const [step, setStep] = useState(0);
  const [choices, setChoices] = useState({ share_logs: true, caregiver: false });
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const doctor: Doctor = view.doctor;
  useEffect(() => { void i18n.changeLanguage(view.language); }, [view.language, i18n]);

  if (step === 0)
    return (
      <Screen>
        <h1 className="text-2xl font-bold">{t("onboarding.consent_title")}</h1>
        <ul className="space-y-3 text-base">
          {["consent_purpose", "consent_data", "consent_who", "consent_rights"].map((k) => (
            <li key={k} className="flex gap-2"><Check aria-hidden className="mt-1 h-5 w-5 shrink-0 text-risk-green" />{t(`onboarding.${k}`, { doctor: doctor.name })}</li>
          ))}
        </ul>
        <p className="rounded-xl bg-amber-100 p-3 text-sm font-semibold text-amber-950">{t("onboarding.consent_synthetic")}</p>
        <fieldset className="space-y-3">
          <Toggle label={t("onboarding.choice_share_logs")} checked={choices.share_logs} onChange={(v) => setChoices({ ...choices, share_logs: v })} />
          {view.caregiver_allowed && (
            <Toggle label={t("onboarding.choice_caregiver")} checked={choices.caregiver} onChange={(v) => setChoices({ ...choices, caregiver: v })} />
          )}
        </fieldset>
        <BigButton onClick={() => setStep(1)}>{t("onboarding.accept")}</BigButton>
      </Screen>
    );
  if (step === 1)
    return (
      <Screen>
        <h1 className="text-2xl font-bold">{t("onboarding.language_title")}</h1>
        <LangPicker />
        <BigButton onClick={() => setStep(2)}>{t("common.next")}</BigButton>
      </Screen>
    );
  if (step >= 2 && step <= 4)
    return (
      <Screen>
        <p className="text-sm text-slate-500">{step - 1} / 3</p>
        <p className="text-xl">{t(`onboarding.tour_${step - 1}`)}</p>
        <BigButton onClick={() => setStep(step + 1)}>{t("common.next")}</BigButton>
      </Screen>
    );
  return (
    <Screen>
      <Watch aria-hidden className="mx-auto h-16 w-16 text-brand" />
      <h1 className="text-center text-2xl font-bold">{t("onboarding.wearable_title")}</h1>
      <p className="text-center">{t("onboarding.wearable_body")}</p>
      <BigButton onClick={() => setConnected(true)} disabled={connected}>
        <Bluetooth aria-hidden className="h-5 w-5" /> {connected ? t("onboarding.connected") : t("onboarding.connect")}
      </BigButton>
      <BigButton disabled={!connected || busy} onClick={async () => { setBusy(true); await onAccept(i18n.language, choices); }}>
        {t("onboarding.start")}
      </BigButton>
    </Screen>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex min-h-12 items-center gap-3 rounded-xl border-2 border-slate-200 p-3 text-base dark:border-slate-700">
      <input type="checkbox" className="h-6 w-6" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}
