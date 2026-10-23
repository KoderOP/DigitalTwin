import { useMemo, useState } from "react";
import { Moon, Search, WifiOff } from "lucide-react";
import type { Level, Summary } from "../types";
import type { PortalState } from "@shared/types";
import { PortalStatusBadge } from "@shared/components/StatusBadges";
import { LevelBadge } from "@shared/components/LevelBadge";
import { TREND_ARROW, pct } from "@shared/lib/format";

const ORDER: Record<Level, number> = { RED: 0, HIGH: 1, AMBER: 2, GREEN: 3 };

export function sortAndFilter(rows: Summary[], search: string, level: Level | "ALL", sort: "risk" | "id" | "glucose"): Summary[] {
  const q = search.trim().toLowerCase();
  return rows
    .filter((r) => (level === "ALL" || r.level === level) && (!q || r.patient_id.toLowerCase().includes(q)))
    .sort((a, b) => {
      if (sort === "id") return a.patient_id.localeCompare(b.patient_id);
      if (sort === "glucose") return (b.g_now ?? 0) - (a.g_now ?? 0);
      return ORDER[a.level] - ORDER[b.level] || (b.risk ?? 0) - (a.risk ?? 0);
    });
}

export interface PortalInfo { state: PortalState; assigned_to_me: boolean }

export function CohortList({ rows, selected, onSelect, portal, bulk }: {
  rows: Summary[]; selected: string | null; onSelect: (id: string) => void;
  portal?: Record<string, PortalInfo>;
  bulk?: { picked: Set<string>; toggle: (id: string) => void; invite: () => void; newPatient: () => void; busy: boolean };
}) {
  const [search, setSearch] = useState("");
  const [level, setLevel] = useState<Level | "ALL">("ALL");
  const [sort, setSort] = useState<"risk" | "id" | "glucose">("risk");
  const shown = useMemo(() => sortAndFilter(rows, search, level, sort), [rows, search, level, sort]);
  const counts = useMemo(() => rows.reduce<Record<string, number>>((acc, r) => ({ ...acc, [r.level]: (acc[r.level] ?? 0) + 1 }), {}), [rows]);

  return (
    <nav aria-label="Patient cohort" className="flex h-full flex-col">
      <div className="space-y-2 border-b border-slate-200 p-3 dark:border-slate-800">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Cohort ({rows.length})</h2>
          <span className="text-[11px] text-slate-500">sorted by {sort}</span>
        </div>
        <label className="relative block">
          <span className="sr-only">Search patient ID</span>
          <Search aria-hidden className="absolute left-2 top-2 h-4 w-4 text-slate-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search ID (TWN-…)"
            className="w-full rounded-md border border-slate-300 bg-white py-1.5 pl-8 pr-2 text-sm dark:border-slate-700 dark:bg-slate-800"
          />
        </label>
        <div className="flex flex-wrap gap-1" role="group" aria-label="Filter by risk level">
          {(["ALL", "RED", "AMBER", "HIGH", "GREEN"] as const).map((l) => (
            <button
              key={l}
              onClick={() => setLevel(l)}
              aria-pressed={level === l}
              className={`rounded-md border px-2 py-0.5 text-[11px] font-medium ${level === l ? "border-brand bg-brand text-white" : "border-slate-300 text-slate-600 dark:border-slate-700 dark:text-slate-300"}`}
            >
              {l === "HIGH" ? "HIGH NOW" : l}
              {l !== "ALL" && ` ${counts[l] ?? 0}`}
            </button>
          ))}
        </div>
        {bulk && (
          <div className="flex flex-wrap gap-1">
            <button disabled={bulk.picked.size === 0 || bulk.busy} onClick={bulk.invite}
              className="rounded-md border border-brand px-2 py-0.5 text-[11px] font-medium text-brand disabled:opacity-40">
              Bulk invite ({bulk.picked.size})
            </button>
            <button disabled={bulk.busy} onClick={bulk.newPatient} className="rounded-md border border-slate-300 px-2 py-0.5 text-[11px] dark:border-slate-600">
              + New synthetic patient
            </button>
          </div>
        )}
        <label className="flex items-center gap-2 text-[11px] text-slate-500">
          Sort
          <select value={sort} onChange={(e) => setSort(e.target.value as typeof sort)} className="rounded border border-slate-300 bg-white px-1 py-0.5 dark:border-slate-700 dark:bg-slate-800">
            <option value="risk">Risk</option>
            <option value="glucose">Glucose</option>
            <option value="id">ID</option>
          </select>
        </label>
      </div>
      <ul className="flex-1 overflow-y-auto">
        {shown.map((r) => {
          const t = TREND_ARROW[r.trend];
          return (
            <li key={r.patient_id}>
              <button
                onClick={() => onSelect(r.patient_id)}
                aria-current={selected === r.patient_id}
                className={`flex w-full flex-col gap-1 border-b border-slate-100 px-3 py-2 text-left hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/60 ${selected === r.patient_id ? "bg-sky-50 dark:bg-slate-800" : ""}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1 font-mono text-xs font-semibold text-slate-800 dark:text-slate-100">
                    {bulk && portal?.[r.patient_id]?.assigned_to_me && ["NOT_ENROLLED", "REVOKED"].includes(portal[r.patient_id].state) && (
                      <input type="checkbox" aria-label={`select ${r.patient_id} for bulk invite`} checked={bulk.picked.has(r.patient_id)}
                        onClick={(e) => e.stopPropagation()} onChange={() => bulk.toggle(r.patient_id)} />
                    )}
                    {r.patient_id}
                  </span>
                  <LevelBadge level={r.level} />
                </div>
                {portal?.[r.patient_id] && (
                  <div className="flex items-center gap-1 text-[10px] text-slate-500">
                    <PortalStatusBadge state={portal[r.patient_id].state} />
                    {!portal[r.patient_id].assigned_to_me && <span>other doctor</span>}
                  </div>
                )}
                <div className="flex items-center justify-between text-[11px] text-slate-600 dark:text-slate-400">
                  <span>
                    {r.age}
                    {r.sex} · A1c {r.hba1c.toFixed(1)}% {r.insulin && "· insulin"}
                  </span>
                  <span className="font-mono text-sm text-slate-900 dark:text-slate-100" aria-label={`glucose ${r.g_now} mg/dL, ${t.label}`}>
                    {r.cgm != null ? Math.round(r.cgm) : r.g_now != null ? `~${Math.round(r.g_now)}` : "–"} <span aria-hidden>{t.arrow}</span>
                  </span>
                </div>
                <div className="flex items-center justify-between text-[11px] text-slate-500">
                  <span>
                    risk {pct(r.risk)}
                    {r.minutes_to_spike != null && r.level !== "GREEN" && ` · ~${r.minutes_to_spike} min`}
                  </span>
                  <span className="flex items-center gap-1">
                    {r.nocturnal_flag && <Moon aria-label={r.nocturnal_flag} className="h-3 w-3" />}
                    {r.data_quality !== "good" && <WifiOff aria-label={`data quality ${r.data_quality}`} className="h-3 w-3 text-risk-amber" />}
                    {r.active_alerts > 0 && <span className="rounded bg-slate-200 px-1 dark:bg-slate-700">{r.active_alerts} alert</span>}
                  </span>
                </div>
              </button>
            </li>
          );
        })}
        {shown.length === 0 && <li className="p-4 text-sm text-slate-500">No patients match.</li>}
      </ul>
    </nav>
  );
}
