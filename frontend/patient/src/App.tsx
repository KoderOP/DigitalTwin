import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Activity, CalendarDays, FlaskConical, HeartPulse, Home as HomeIcon, Moon, PlusCircle, Sun, UserRound, WifiOff } from "lucide-react";
import { PatientLevelBadge } from "@shared/components/StatusBadges";
import { AlertCard } from "@shared/components/AlertCard";
import { papi, session, useLiveView } from "./api";
import type { AnyView, CaregiverView, PatientView, PendingView } from "./types";
import { ConsentFlow, InviteFlow } from "./screens/Onboarding";
import { Home } from "./screens/Home";
import { MyDay } from "./screens/MyDay";
import { TryIt } from "./screens/TryIt";
import { QuickLog } from "./screens/QuickLog";
import { Care } from "./screens/Care";
import { Me } from "./screens/Me";
import { Panel, Screen } from "./screens/ui";
import { DemoAccounts } from "./screens/DemoAccounts";

type Mode = { kind: "invite" | "preview" | "caregiver" | "session"; token: string | null };

function initialMode(): Mode {
  const q = new URLSearchParams(location.search);
  for (const kind of ["invite", "preview", "caregiver"] as const) {
    const tok = q.get(kind);
    if (tok) return { kind, token: tok };
  }
  return { kind: "session", token: session.get() };
}

function useDark(): [boolean, () => void] {
  const [dark, setDark] = useState(() => { try { return localStorage.getItem("theme") === "dark"; } catch { return false; } });
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try { localStorage.setItem("theme", dark ? "dark" : "light"); } catch { /* blocked */ }
  }, [dark]);
  return [dark, () => setDark((d) => !d)];
}

export default function App() {
  const { t, i18n } = useTranslation();
  const [mode, setMode] = useState<Mode>(initialMode);
  const [dark, toggleDark] = useDark();
  const [ended, setEnded] = useState<string | null>(null);

  const token = mode.kind === "invite" ? null : mode.token;
  const { view, error, offline, refresh } = useLiveView(ended ? null : token);

  useEffect(() => { if (view?.language && view.language !== i18n.language) void i18n.changeLanguage(view.language); }, [view?.language, i18n]);
  useEffect(() => {
    if (error && (error.status === 401 || error.status === 403) && mode.kind === "session") {
      session.clear();
      setEnded(error.message.includes("PAUSED") ? t("state.paused") : t("state.revoked"));
    }
  }, [error, mode.kind, t]);

  const header = (
    <header className="sticky top-0 z-20 bg-white/95 shadow-sm backdrop-blur dark:bg-slate-900/95">
      <div role="note" className="bg-amber-400 px-3 py-1 text-center text-xs font-bold text-black">{t("app.synthetic")}</div>
      <div className="mx-auto flex max-w-md items-center justify-between px-4 py-2">
        <span className="flex items-center gap-2 text-lg font-bold"><HeartPulse aria-hidden className="h-6 w-6 text-brand" />{t("app.title")}</span>
        <button onClick={toggleDark} aria-label={dark ? "Light mode" : "Dark mode"} className="min-h-11 min-w-11 rounded-full border-2 border-slate-300 p-2">
          {dark ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
        </button>
      </div>
      {mode.kind === "preview" && <div className="bg-violet-700 px-3 py-1 text-center text-xs font-semibold text-white">{t("state.preview")}</div>}
      {offline && <div className="flex items-center justify-center gap-1 bg-slate-700 px-3 py-1 text-xs text-white"><WifiOff aria-hidden className="h-3 w-3" />{t("app.offline")}</div>}
    </header>
  );

  let body: JSX.Element;
  if (mode.kind === "invite" && mode.token) {
    body = <InviteFlow invite={mode.token} onVerified={(tok) => {
      session.set(tok);
      history.replaceState(null, "", location.pathname);
      setMode({ kind: "session", token: tok });
    }} />;
  } else if (ended) {
    body = (
      <>
        <Screen><p role="alert" className="text-center text-xl">{ended}</p></Screen>
        <DemoAccounts fallback="" onLogin={(tok, lang) => { session.set(tok); void i18n.changeLanguage(lang); setEnded(null); setMode({ kind: "session", token: tok }); }} />
      </>
    );
  } else if (!token) {
    body = <DemoAccounts fallback={t("state.invalid")} onLogin={(tok, lang) => { session.set(tok); void i18n.changeLanguage(lang); setMode({ kind: "session", token: tok }); }} />;
  } else if (!view) {
    body = <Screen><p>{error ? error.message : t("common.loading")}</p></Screen>;
  } else if (view.state === "CONSENT_PENDING") {
    body = <ConsentFlow view={view as PendingView} onAccept={async (lang, choices) => { await papi.consent(token, lang, choices); refresh(); }} />;
  } else if (view.state === "PAUSED") {
    body = <Screen><p className="text-center text-xl">{t("state.paused")}</p></Screen>;
  } else if (view.state === "CAREGIVER") {
    body = <CaregiverScreen v={view as CaregiverView} />;
  } else {
    body = <Main v={view as PatientView} token={token} readOnly={mode.kind === "preview"} onWithdrawn={() => { session.clear(); setEnded(t("me.withdrawn")); }} refresh={refresh} />;
  }
  return <div className="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-50">{header}{body}</div>;
}

function Main({ v, token, readOnly, onWithdrawn, refresh }: { v: PatientView; token: string; readOnly: boolean; onWithdrawn: () => void; refresh: () => void }) {
  const { t } = useTranslation();
  const [tab, setTab] = useState("home");
  const tabs = useMemo(() => [
    { id: "home", Icon: HomeIcon, label: t("nav.home"), on: true },
    { id: "day", Icon: CalendarDays, label: t("nav.day"), on: true },
    { id: "log", Icon: PlusCircle, label: t("nav.log"), on: v.features.quick_log && !readOnly },
    { id: "try", Icon: FlaskConical, label: t("nav.try"), on: v.features.try_it },
    { id: "care", Icon: Activity, label: t("nav.care"), on: true, badge: v.alerts.filter((a) => !a.seen).length },
    { id: "me", Icon: UserRound, label: t("nav.me"), on: true },
  ].filter((x) => x.on), [t, v.features, v.alerts, readOnly]);
  return (
    <>
      <main className="mx-auto max-w-md px-3 pb-28 pt-3">
        {tab === "home" && <Home v={v} onGo={setTab} />}
        {tab === "day" && <MyDay v={v} />}
        {tab === "log" && <QuickLog token={token} onLogged={refresh} />}
        {tab === "try" && <TryIt token={token} />}
        {tab === "care" && <Care v={v} token={token} readOnly={readOnly} onChanged={refresh} />}
        {tab === "me" && <Me v={v} token={token} readOnly={readOnly} onWithdrawn={onWithdrawn} />}
      </main>
      <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-20 border-t border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <ul className="mx-auto flex max-w-md">
          {tabs.map((x) => (
            <li key={x.id} className="flex-1">
              <button onClick={() => setTab(x.id)} aria-current={tab === x.id ? "page" : undefined}
                className={`relative flex min-h-16 w-full flex-col items-center justify-center gap-0.5 text-[11px] font-semibold ${tab === x.id ? "text-brand" : "text-slate-500"}`}>
                <x.Icon aria-hidden className="h-6 w-6" />{x.label}
                {"badge" in x && x.badge ? <span className="absolute right-3 top-1 rounded-full bg-risk-red px-1.5 text-[10px] text-white">{x.badge}</span> : null}
              </button>
            </li>
          ))}
        </ul>
      </nav>
    </>
  );
}

function CaregiverScreen({ v }: { v: CaregiverView }) {
  const { t } = useTranslation();
  const labels = { understood: "", yes: "", no: "", firstAid: t("care.first_aid"), call: t("care.call"), confidence: t("home.confidence") };
  return (
    <main className="mx-auto max-w-md space-y-4 px-3 py-4">
      <p className="rounded-lg bg-violet-100 p-2 text-center text-sm text-violet-900">{t("state.caregiver")}</p>
      <Panel>
        <PatientLevelBadge level={v.status.level} label={t(`levels.${v.status.level}`)} />
        <p className="mt-3 text-2xl font-bold">{v.status.sentence}</p>
        <p className="mt-2 text-3xl">{v.glucose.value ?? "–"} {v.glucose.unit} <span aria-hidden>{v.glucose.trend_icon}</span> <span className="text-base">{v.glucose.trend_text}</span></p>
      </Panel>
      {v.alerts.map((a) => <AlertCard key={a.id} a={a} labels={labels} readOnly />)}
      <p className="text-center text-xs text-slate-500">{v.disclaimer}</p>
    </main>
  );
}

export type { AnyView };
