import { useState } from "react";
import { Pause, Play, RotateCcw, SkipForward, Zap } from "lucide-react";
import { api } from "../api";
import type { SimState } from "../types";

const SPEED_LABEL: Record<number, string> = { 1: "Real-time", 10: "10x", 60: "60x", 300: "300x", 900: "900x" };

export function DemoControls({ state, patientId, onToast }: { state: SimState | null; patientId: string | null; onToast: (m: string) => void }) {
  const [busy, setBusy] = useState(false);
  if (!state) return null;
  const run = async (fn: () => Promise<unknown>, msg?: string) => {
    setBusy(true);
    try {
      await fn();
      if (msg) onToast(msg);
    } catch (e) {
      onToast(`Error: ${String(e)}`);
    } finally {
      setBusy(false);
    }
  };
  const btn = "flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium disabled:opacity-50";
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex items-center gap-1" role="group" aria-label="Stream speed">
        <span className="mr-1 text-[11px] uppercase tracking-wide text-slate-500">Speed</span>
        {state.speeds.map((s) => (
          <button key={s} aria-pressed={state.speed === s} onClick={() => run(() => api.speed(s))}
            className={`${btn} ${state.speed === s ? "border-brand bg-brand text-white" : "border-slate-300 dark:border-slate-600"}`}>
            {SPEED_LABEL[s] ?? `${s}x`}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-1">
        <button className={`${btn} border-slate-300 dark:border-slate-600`} onClick={() => run(() => api.pause(!state.paused))} aria-label={state.paused ? "Resume stream" : "Pause stream"}>
          {state.paused ? <Play className="h-3 w-3" /> : <Pause className="h-3 w-3" />} {state.paused ? "Resume" : "Pause"}
        </button>
        <button className={`${btn} border-slate-300 dark:border-slate-600`} disabled={busy} onClick={() => run(() => api.step())}><SkipForward className="h-3 w-3" aria-hidden /> +5 min</button>
        <button className={`${btn} border-slate-300 dark:border-slate-600`} disabled={busy} onClick={() => run(() => api.reset(), "Simulation reset")}><RotateCcw className="h-3 w-3" aria-hidden /> Reset</button>
      </div>
      <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Inject event for the selected patient">
        <span className="mr-1 flex items-center gap-1 text-[11px] uppercase tracking-wide text-slate-500"><Zap className="h-3 w-3" aria-hidden />Inject</span>
        {state.injections.map((i) => (
          <button key={i.event} disabled={!patientId || busy} title={patientId ? i.label : "Select a patient first"}
            onClick={() => patientId && run(() => api.inject(patientId, i.event), `Injected for ${patientId}: ${i.label}`)}
            className={`${btn} border-risk-amber text-amber-800 hover:bg-amber-50 dark:text-amber-300 dark:hover:bg-amber-950`}>
            {i.label.split(" (")[0]}
          </button>
        ))}
      </div>
    </div>
  );
}
