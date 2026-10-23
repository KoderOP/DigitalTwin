import { ArrowDown, ArrowUp } from "lucide-react";
import type { Prediction } from "../types";
import { COLORS } from "@shared/lib/format";

/** "Why this alert?": grouped SHAP / Integrated-Gradients attributions with plain-language reasons. */
export function ExplainPanel({ p }: { p: Prediction }) {
  const f = p.explanation ?? [];
  if (!f.length) return <p className="text-sm text-slate-500">Explanation is computed for the selected patient…</p>;
  const max = Math.max(...f.map((x) => Math.abs(x.contribution)), 1e-6);
  const method = p.model.startsWith("deep") ? "Integrated Gradients (Aumann-Shapley)" : "TreeSHAP";
  return (
    <div>
      <ul className="space-y-2">
        {f.map((x) => {
          const up = x.contribution > 0;
          const w = `${(Math.abs(x.contribution) / max) * 100}%`;
          return (
            <li key={x.factor}>
              <div className="flex items-center justify-between text-xs">
                <span className="flex items-center gap-1 font-semibold text-slate-800 dark:text-slate-100">
                  {up ? <ArrowUp aria-hidden className="h-3 w-3" style={{ color: COLORS.red }} /> : <ArrowDown aria-hidden className="h-3 w-3" style={{ color: COLORS.blue }} />}
                  {x.title}
                  <span className="rounded bg-slate-100 px-1 text-[10px] font-normal text-slate-500 dark:bg-slate-800">{x.source}</span>
                </span>
                <span className="font-mono text-[11px] text-slate-500">{up ? "raises" : "lowers"} risk · {(x.share * 100).toFixed(0)}%</span>
              </div>
              <div className="mt-0.5 h-2 w-full rounded bg-slate-100 dark:bg-slate-800" aria-hidden>
                <div className="h-2 rounded" style={{ width: w, backgroundColor: up ? COLORS.red : COLORS.blue, backgroundImage: up ? "repeating-linear-gradient(45deg, transparent 0 3px, rgba(255,255,255,.35) 3px 5px)" : undefined }} />
              </div>
              <p className="mt-0.5 text-xs text-slate-600 dark:text-slate-300">{x.text}</p>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-[10px] text-slate-500">
        Attribution: {method} on the {p.model} model, grouped into clinical factors. It shows what drove the prediction, not causal proof.
      </p>
    </div>
  );
}
