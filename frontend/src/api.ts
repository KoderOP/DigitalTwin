import { useEffect, useRef, useState } from "react";
import type { AuditRow, Detail, Meta, ScenarioReq, SimState, Summary, WhatIfResult, Alert } from "./types";

export const USER = "dr.demo"; // pseudonymous clinician identity for the audit trail

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}
const post = <T,>(path: string, body: unknown) => req<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  meta: () => req<Meta>("/api/meta"),
  patient: (id: string) => req<Detail>(`/api/patients/${id}?user=${USER}`),
  whatIf: (id: string, scenarios: ScenarioReq[]) => post<WhatIfResult>(`/api/patients/${id}/whatif`, { scenarios, user: USER }),
  ack: (id: string, alertId: number) => post<Alert>(`/api/patients/${id}/alerts/${alertId}/ack`, { user: USER }),
  note: (id: string, text: string) => post(`/api/patients/${id}/notes`, { user: USER, text }),
  intervention: (id: string, kind: string, detail: string) => post(`/api/patients/${id}/interventions`, { user: USER, kind, detail }),
  speed: (speed: number) => post<SimState>("/api/sim/speed", { speed }),
  pause: (paused: boolean) => post<SimState>("/api/sim/pause", { paused }),
  step: () => post<SimState>("/api/sim/step", {}),
  reset: () => post<SimState>("/api/sim/reset", {}),
  inject: (patient_id: string, event: string) => post<{ description: string }>("/api/sim/inject", { patient_id, event }),
  audit: (patient_id?: string) => req<AuditRow[]>(`/api/audit?limit=30${patient_id ? `&patient_id=${patient_id}` : ""}`),
};

export interface LiveData {
  connected: boolean;
  state: SimState | null;
  cohort: Summary[];
  detail: Detail | null;
  newAlerts: Alert[];
}

/** WebSocket hook: cohort ticks for everyone, full twin detail for the subscribed patient. */
export function useLive(selected: string | null): LiveData & { setDetail: (d: Detail) => void } {
  const [connected, setConnected] = useState(false);
  const [state, setState] = useState<SimState | null>(null);
  const [cohort, setCohort] = useState<Summary[]>([]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [newAlerts, setNewAlerts] = useState<Alert[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const selRef = useRef<string | null>(selected);
  selRef.current = selected;

  useEffect(() => {
    let closed = false;
    let retry: ReturnType<typeof setTimeout>;
    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/ws`);
      wsRef.current = ws;
      ws.onopen = () => {
        setConnected(true);
        if (selRef.current) ws.send(JSON.stringify({ type: "subscribe", patient_id: selRef.current }));
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) retry = setTimeout(connect, 1500);
      };
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.type === "tick") {
          setState(msg.state);
          setCohort(msg.cohort);
          if (msg.new_alerts?.length) setNewAlerts(msg.new_alerts);
        } else if (msg.type === "patient" && msg.data?.header?.patient_id === selRef.current) {
          setDetail(msg.data);
        }
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      wsRef.current?.close();
    };
  }, []);

  useEffect(() => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(selected ? { type: "subscribe", patient_id: selected } : { type: "unsubscribe" }));
    }
    if (!selected) setDetail(null);
  }, [selected]);

  return { connected, state, cohort, detail, newAlerts, setDetail };
}
