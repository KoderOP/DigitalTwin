import { useEffect, useRef, useState } from "react";
import type { AnyView, TryResult } from "./types";

const DEVICE_KEY = "dt_device_id";
const TOKEN_KEY = "dt_patient_token";
const VIEW_KEY = "dt_last_view";
let memDevice: string | null = null;
let memToken: string | null = null;

const ls = {
  get: (k: string) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* storage blocked */ } },
  del: (k: string) => { try { localStorage.removeItem(k); } catch { /* storage blocked */ } },
};

/** Stable per-browser device id: the server binds the patient session to its hash. */
export function deviceId(): string {
  const stored = ls.get(DEVICE_KEY) ?? memDevice;
  if (stored) return stored;
  const id = (globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`).replace(/[^a-zA-Z0-9-]/g, "");
  memDevice = id;
  ls.set(DEVICE_KEY, id);
  return id;
}

export const session = {
  get: () => ls.get(TOKEN_KEY) ?? memToken,
  set: (t: string) => { memToken = t; ls.set(TOKEN_KEY, t); },
  clear: () => { memToken = null; ls.del(TOKEN_KEY); ls.del(VIEW_KEY); },
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function call<T>(path: string, token?: string | null, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json", "X-Device-Id": deviceId() };
  if (token) headers.Authorization = `Bearer ${token}`;
  const r = await fetch(path, { ...init, headers: { ...headers, ...(init?.headers as Record<string, string>) } });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail ?? msg; } catch { /* not json */ }
    throw new ApiError(r.status, typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json() as Promise<T>;
}
const post = <T,>(path: string, body: unknown, token?: string | null) => call<T>(path, token, { method: "POST", body: JSON.stringify(body) });

export interface DemoAccount { id: string; label: string; language: string; patient_id: string; doctor: string; state: string }

export const papi = {
  demoAccounts: () => call<DemoAccount[]>("/api/portal/demo/accounts"),
  demoLogin: (account: string) => post<{ token: string; patient_id: string; language: string }>("/api/portal/demo/login", { account, device_id: deviceId() }),
  open: (invite: string) => post<{ doctor: { name: string; title: string }; language: string; dev_mode: boolean; otp_ttl_min: number }>(
    "/api/portal/invite/open", { token: invite, device_id: deviceId() }),
  devOtp: (invite: string) => call<{ message: string | null }>(`/api/portal/dev/otp?token=${encodeURIComponent(invite)}`),
  verify: (invite: string, otp: string) => post<{ token: string; language: string }>("/api/portal/invite/verify", { token: invite, otp, device_id: deviceId() }),
  me: (t: string) => call<AnyView>("/api/portal/me", t),
  consent: (t: string, language: string, choices: Record<string, boolean>) => post<{ state: string }>("/api/portal/me/consent", { accept: true, language, choices }, t),
  withdraw: (t: string) => post<{ state: string }>("/api/portal/me/withdraw", {}, t),
  language: (t: string, language: string) => post("/api/portal/me/language", { language }, t),
  log: (t: string, body: Record<string, unknown>) => post<{ ok: boolean; safety?: { first_aid: { title: string; steps: string[]; emergency: string; contact: string } } }>(
    "/api/portal/me/logs", body, t),
  tryit: (t: string, preset: string) => post<TryResult>("/api/portal/me/tryit", { preset }, t),
  ack: (t: string, id: number, understood: boolean | null) => post(`/api/portal/me/alerts/${id}/ack`, { understood }, t),
  cardDone: (t: string, id: number) => post(`/api/portal/me/cards/${id}/done`, {}, t),
  msgRead: (t: string, id: number) => post(`/api/portal/me/messages/${id}/read`, {}, t),
  accessLog: (t: string) => call<{ ts: string; who: string; action: string }[]>("/api/portal/me/access-log", t),
  caregiverLink: (t: string) => post<{ link: string }>("/api/portal/me/caregiver-link", {}, t),
};

/**
 * Live view: WebSocket push (every 5 simulated minutes) plus a slow polling fallback for flaky
 * low-bandwidth networks. The last view is cached for the offline shell.
 */
export function useLiveView(token: string | null): { view: AnyView | null; error: ApiError | null; offline: boolean; refresh: () => void } {
  const [view, setView] = useState<AnyView | null>(() => {
    try { const v = ls.get(VIEW_KEY); return v ? (JSON.parse(v) as AnyView) : null; } catch { return null; }
  });
  const [error, setError] = useState<ApiError | null>(null);
  const [offline, setOffline] = useState(false);
  const tick = useRef(0);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!token) return;
    let stop = false;
    let ws: WebSocket | null = null;
    const accept = (v: AnyView) => {
      if (stop) return;
      setView(v);
      setError(null);
      setOffline(false);
      if (v.state === "ACTIVE") ls.set(VIEW_KEY, JSON.stringify(v));
    };
    const load = () => papi.me(token).then(accept).catch((e: unknown) => {
      if (e instanceof ApiError) setError(e);
      else setOffline(true);
    });
    void load();
    const poll = setInterval(load, 20000);
    try {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws/patient?token=${encodeURIComponent(token)}&device=${encodeURIComponent(deviceId())}`);
      ws.onmessage = (ev) => {
        const m = JSON.parse(ev.data);
        if (m.type === "view") accept(m.data);
        if (m.type === "state") void load();
      };
      ws.onclose = () => { tick.current += 1; if (!stop) void load(); };
    } catch { /* websocket unavailable: polling continues */ }
    return () => { stop = true; clearInterval(poll); ws?.close(); };
  }, [token, nonce]);

  return { view, error, offline, refresh: () => setNonce((n) => n + 1) };
}
