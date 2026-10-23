import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { UserRound } from "lucide-react";
import { papi, type DemoAccount } from "../api";
import { BigButton, Screen } from "./ui";

/** DEMO ONLY landing screen: pre-activated synthetic patient accounts (hidden when the server disables them). */
export function DemoAccounts({ onLogin, fallback }: { onLogin: (token: string, language: string) => void; fallback: string }) {
  const { t } = useTranslation();
  const [accts, setAccts] = useState<DemoAccount[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { papi.demoAccounts().then(setAccts).catch(() => setAccts([])); }, []);
  if (accts === null) return <Screen><p>{t("common.loading")}</p></Screen>;
  if (accts.length === 0) return <Screen><p className="text-center text-xl">{fallback}</p></Screen>;
  return (
    <Screen>
      <h1 className="text-2xl font-bold">{t("demo.title")}</h1>
      <p>{t("demo.subtitle")}</p>
      <ul className="space-y-3" data-testid="demo-accounts">
        {accts.map((a) => (
          <li key={a.id}>
            <BigButton variant="secondary" onClick={() => papi.demoLogin(a.id).then((r) => onLogin(r.token, r.language)).catch((e) => setErr(String(e)))}>
              <UserRound aria-hidden className="h-6 w-6 shrink-0" />
              <span className="flex flex-col items-start text-left">
                <span>{a.label}</span>
                <span className="text-xs font-normal text-slate-500">{a.patient_id} · {a.doctor}</span>
              </span>
            </BigButton>
          </li>
        ))}
      </ul>
      {err && <p role="alert">{err}</p>}
      <p className="text-sm text-slate-500">{t("demo.or_invite")}</p>
    </Screen>
  );
}
