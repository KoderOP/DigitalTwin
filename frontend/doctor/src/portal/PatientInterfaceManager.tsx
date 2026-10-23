import { useCallback, useEffect, useState } from "react";
import QRCode from "qrcode";
import { Ban, Eye, EyeOff, MessageSquarePlus, Pause, Play, RefreshCw, Rocket, Send, Settings, Smartphone } from "lucide-react";
import { PortalStatusBadge } from "@shared/components/StatusBadges";
import { portal, PortalError, type Manager } from "./portalApi";
import { LaunchWizard } from "./LaunchWizard";

function useCountdown(seconds: number | undefined): string {
  const [left, setLeft] = useState(seconds ?? 0);
  useEffect(() => { setLeft(seconds ?? 0); }, [seconds]);
  useEffect(() => { const id = setInterval(() => setLeft((s) => Math.max(s - 1, 0)), 1000); return () => clearInterval(id); }, []);
  const h = Math.floor(left / 3600), m = Math.floor((left % 3600) / 60), s = left % 60;
  return left <= 0 ? "expired" : `${h}h ${String(m).padStart(2, "0")}m ${String(s).padStart(2, "0")}s`;
}

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "–");

/** Doctor-side control of one patient's app: lifecycle, invite/QR, settings, preview, engagement, two-way messages. */
export function PatientInterfaceManager({ pid, tick, onChanged }: { pid: string; tick: string | undefined; onChanged?: () => void }) {
  const [m, setM] = useState<Manager | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [wizard, setWizard] = useState<"launch" | "edit" | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const [card, setCard] = useState("");

  const load = useCallback(() => portal.manager(pid).then((x) => { setM(x); setErr(null); }).catch((e: PortalError) => setErr(e.message)), [pid]);
  useEffect(() => { void load(); setPreview(null); }, [load]);
  useEffect(() => { void load(); }, [tick, load]);
  useEffect(() => {
    if (m?.invite?.link) QRCode.toDataURL(m.invite.link, { margin: 1, width: 200, errorCorrectionLevel: "M" }).then(setQr).catch(() => setQr(null));
    else setQr(null);
  }, [m?.invite?.link]);
  const countdown = useCountdown(m?.invite?.seconds_left);

  const act = async (fn: () => Promise<unknown>) => {
    try { await fn(); await load(); onChanged?.(); } catch (e) { setErr(e instanceof PortalError ? e.message : String(e)); }
  };
  if (!m) return <p className="text-sm text-slate-500">{err ?? "Loading patient interface…"}</p>;
  const st = m.state;
  const e = m.engagement;
  const btn = "inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium disabled:opacity-40";
  const mine = m.assigned_to_me;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <PortalStatusBadge state={st} />
        <span className="text-slate-500">Care team: <b>{m.doctor.name}</b></span>
        <span className="text-slate-500">Last patient activity: {fmt(m.last_activity)}</span>
        {m.consent && <span className="text-slate-500">Consent v{m.consent.version}: logs shared {m.consent.choices.share_logs ? "yes" : "no"}, caregiver {m.consent.choices.caregiver ? "yes" : "no"}{m.consent.withdrawn_at && " (withdrawn)"}</span>}
      </div>
      {!mine && <p className="rounded bg-slate-100 p-2 text-xs dark:bg-slate-800">This patient is assigned to {m.doctor.name}. Only the assigned doctor can launch or change the patient interface.</p>}
      {err && <p role="alert" className="rounded bg-red-50 p-2 text-xs text-red-800">{err}</p>}

      <div className="flex flex-wrap gap-2">
        {(st === "NOT_ENROLLED" || st === "REVOKED") && (
          <button disabled={!mine} onClick={() => setWizard("launch")} className={`${btn} border-brand bg-brand text-white`}><Rocket className="h-3 w-3" aria-hidden /> Launch patient interface</button>
        )}
        {(st === "INVITED" || st === "CONSENT_PENDING") && (<>
          <button disabled={!mine} onClick={() => act(() => portal.resend(pid))} className={btn}><Send className="h-3 w-3" aria-hidden /> Resend</button>
          <button disabled={!mine} onClick={() => act(() => portal.regenerate(pid))} className={btn}><RefreshCw className="h-3 w-3" aria-hidden /> Regenerate</button>
        </>)}
        {m.config && st !== "REVOKED" && <button disabled={!mine} onClick={() => setWizard("edit")} className={btn}><Settings className="h-3 w-3" aria-hidden /> Edit settings</button>}
        {st === "ACTIVE" && <button disabled={!mine} onClick={() => act(() => portal.pause(pid))} className={btn}><Pause className="h-3 w-3" aria-hidden /> Pause</button>}
        {st === "PAUSED" && <button disabled={!mine} onClick={() => act(() => portal.resume(pid))} className={btn}><Play className="h-3 w-3" aria-hidden /> Resume</button>}
        {st !== "NOT_ENROLLED" && st !== "REVOKED" && <button disabled={!mine} onClick={() => act(() => portal.revoke(pid))} className={`${btn} border-red-700 text-red-700`}><Ban className="h-3 w-3" aria-hidden /> Revoke</button>}
        {m.config && (
          <button disabled={!mine} onClick={() => preview ? setPreview(null) : act(async () => setPreview((await portal.previewToken(pid)).path))} className={btn}>
            {preview ? <EyeOff className="h-3 w-3" aria-hidden /> : <Eye className="h-3 w-3" aria-hidden />} {preview ? "Hide preview" : "View as patient"}
          </button>
        )}
      </div>

      <div className={`grid gap-3 ${m.invite && st === "INVITED" ? "lg:grid-cols-[220px_1fr]" : ""}`}>
        {m.invite && (st === "INVITED") && (
          <div className="rounded-lg border p-2 text-xs">
            <p className="flex items-center gap-1 font-semibold"><Smartphone className="h-3 w-3" aria-hidden /> Secure single-use invite</p>
            {qr && m.invite.link ? <img src={qr} alt="QR code of the patient invite link" className="my-1 h-40 w-40" /> : <p>Invite {m.invite.status}</p>}
            <p>Expires in <b data-testid="invite-countdown">{countdown}</b></p>
            <p>Sent {m.invite.sends}× · wrong codes {m.invite.attempts}</p>
            {m.invite.link && <a className="break-all text-brand underline" href={m.invite.link} target="_blank" rel="noreferrer">Open patient link (2nd window)</a>}
          </div>
        )}
        <div className="grid gap-2 text-xs sm:grid-cols-4">
          {[
            ["Alerts delivered", e.alerts_delivered], ["Alerts seen", e.alerts_seen], ["Safety alerts", e.safety_alerts], ["Suppressed by cap", e.alerts_suppressed_by_cap],
            ["Logs completed", Object.values(e.logs).reduce((a, b) => a + b, 0)], ["Median time to log", e.median_time_to_log_s != null ? `${e.median_time_to_log_s} s` : "–"],
            ["Messages read", `${e.messages_read}/${e.messages_sent}`], ["Care-plan items done", `${e.cards_done}/${e.cards_total}`],
            ["Alert comprehension", e.alert_comprehension != null ? `${Math.round(e.alert_comprehension * 100)}%` : "–"], ["Alerts / day", e.alerts_per_day ?? "–"], ["Escalations", e.escalations],
          ].map(([k, v]) => (
            <div key={String(k)} className="rounded bg-slate-50 p-2 dark:bg-slate-800"><p className="text-slate-500">{k}</p><p className="font-mono text-base font-semibold">{String(v)}</p></div>
          ))}
          {e.recent_logs.length > 0 && (
            <div className="rounded bg-sky-50 p-2 sm:col-span-4 dark:bg-slate-800" data-testid="recent-logs">
              <p className="font-semibold">Recent patient logs (response channel)</p>
              {e.recent_logs.map((l, i) => <p key={i} className="font-mono">{l.ts_sim.slice(11, 16)} {l.kind}: {JSON.stringify(l.payload)}</p>)}
            </div>
          )}
        </div>
      </div>

      {st === "ACTIVE" && mine && (
        <div className="grid gap-2 md:grid-cols-2">
          <form className="flex gap-2" onSubmit={(ev) => { ev.preventDefault(); if (msg.trim()) void act(() => portal.message(pid, msg.trim())).then(() => setMsg("")); }}>
            <input value={msg} onChange={(ev) => setMsg(ev.target.value)} placeholder="Message to patient…" aria-label="message to patient" className="flex-1 rounded border px-2 py-1 text-xs dark:bg-slate-800" />
            <button className={btn}><Send className="h-3 w-3" aria-hidden /> Send</button>
          </form>
          <form className="flex gap-2" onSubmit={(ev) => { ev.preventDefault(); if (card.trim()) void act(() => portal.card(pid, card.trim(), "")).then(() => setCard("")); }}>
            <input value={card} onChange={(ev) => setCard(ev.target.value)} placeholder="Push care-plan card (e.g. walk 15 min after dinner)…" aria-label="care plan card" className="flex-1 rounded border px-2 py-1 text-xs dark:bg-slate-800" />
            <button className={btn}><MessageSquarePlus className="h-3 w-3" aria-hidden /> Push</button>
          </form>
        </div>
      )}

      {preview && <iframe title="View as patient" src={preview} className="h-[700px] w-full max-w-[400px] rounded-2xl border-8 border-slate-800" />}

      {m.outbox.length > 0 && (
        <details className="text-xs"><summary className="cursor-pointer text-slate-500">Mock SMS / email outbox for this patient (dev)</summary>
          <ul className="mt-1 space-y-1 font-mono">{m.outbox.map((o) => <li key={o.id}>{o.ts.slice(11, 19)} [{o.channel}] → {o.recipient}: {o.body}</li>)}</ul>
        </details>
      )}
      {wizard && <LaunchWizard pid={pid} initial={wizard === "edit" ? m.config : null} mode={wizard} onClose={() => setWizard(null)} onDone={() => { setWizard(null); void load(); onChanged?.(); }} />}
    </div>
  );
}
