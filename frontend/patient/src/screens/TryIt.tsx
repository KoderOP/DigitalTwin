import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Clock, Footprints, Wheat } from "lucide-react";
import { MiniForecast } from "@shared/components/MiniForecast";
import { COLORS } from "@shared/lib/format";
import { papi } from "../api";
import type { TryResult } from "../types";
import { BigButton, Panel } from "./ui";

const PRESETS = [
  { id: "walk15", Icon: Footprints, labels: ["try.before", "try.walk"] },
  { id: "roti_rice", Icon: Wheat, labels: ["try.rice", "try.roti"] },
  { id: "early_dinner", Icon: Clock, labels: ["try.late", "try.early"] },
] as const;

/** Patient-friendly what-if: three plain questions, a before/after chart, one sentence. Estimates only. */
export function TryIt({ token, readOnly = false }: { token: string; readOnly?: boolean }) {
  const { t } = useTranslation();
  const [res, setRes] = useState<TryResult | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const run = async (id: string) => {
    setBusy(id);
    setErr(null);
    try { setRes(await papi.tryit(token, id)); } catch (e) { setErr(String(e)); } finally { setBusy(null); }
  };
  const preset = PRESETS.find((p) => p.id === res?.preset);
  const data = res ? res.times.map((ts, i) => ({ t: new Date(ts).getTime(), mid: res.before[i], after: res.after[i] })) : [];
  return (
    <div className="space-y-4">
      <Panel title={t("try.title")}>
        <p className="mb-3">{t("try.subtitle")}</p>
        <div className="space-y-3">
          {PRESETS.map((p) => (
            <BigButton key={p.id} variant={res?.preset === p.id ? "primary" : "secondary"} disabled={busy !== null || readOnly} onClick={() => run(p.id)}>
              <p.Icon aria-hidden className="h-6 w-6" /> {t(`try.q.${p.id}`)}
            </BigButton>
          ))}
        </div>
      </Panel>
      {err && <p role="alert">{err}</p>}
      {res && preset && (
        <Panel title={res.question}>
          <MiniForecast data={data} low={res.target.low} high={res.target.high} label={res.result} height={180} />
          <div className="mt-2 flex flex-wrap gap-4 text-sm">
            <span className="flex items-center gap-1"><span aria-hidden className="inline-block h-1 w-6 border-t-4 border-dashed" style={{ borderColor: COLORS.blue }} />{t(preset.labels[0])}</span>
            <span className="flex items-center gap-1"><span aria-hidden className="inline-block h-1 w-6" style={{ background: COLORS.green }} />{t(preset.labels[1])}</span>
          </div>
          <p className="mt-3 text-xl font-semibold" data-testid="tryit-result">{res.result}</p>
          <p className="mt-1 text-sm text-slate-500">{res.note}</p>
        </Panel>
      )}
    </div>
  );
}
