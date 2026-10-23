import { useEffect, useRef, useState } from "react";
import { Terminal, X } from "lucide-react";
import { portal } from "./portalApi";

/**
 * DEMO dev console for mock SMS/email delivery (invites, OTP codes, escalations). Real deployments
 * would use an SMS gateway. Nothing here leaves the machine.
 */
export function DevOutbox({ onNew }: { onNew: (text: string) => void }) {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<{ id: number; ts: string; pid: string; channel: string; recipient: string; body: string }[]>([]);
  const last = useRef<number>(0);
  useEffect(() => {
    let stop = false;
    const poll = () => portal.outbox().then((r) => {
      if (stop) return;
      setRows(r);
      const fresh = r.filter((x) => x.id > last.current);
      if (last.current && fresh.length) fresh.reverse().forEach((x) => onNew(`📱 ${x.body}`));
      if (r.length) last.current = Math.max(last.current, r[0].id);
    }).catch(() => undefined);
    void poll();
    const id = setInterval(poll, 4000);
    return () => { stop = true; clearInterval(id); };
  }, [onNew]);
  return (
    <div className="fixed bottom-4 left-4 z-40">
      {open ? (
        <div className="w-[420px] max-w-[90vw] rounded-lg bg-slate-900 p-3 text-xs text-green-300 shadow-xl">
          <div className="mb-1 flex items-center justify-between text-slate-300"><span>Dev outbox: mock SMS / email (demo only)</span><button onClick={() => setOpen(false)} aria-label="close"><X className="h-4 w-4" /></button></div>
          <ul className="max-h-64 space-y-1 overflow-y-auto font-mono">{rows.map((r) => <li key={r.id}>{r.ts.slice(11, 19)} [{r.channel}] {r.recipient}: {r.body}</li>)}</ul>
        </div>
      ) : (
        <button onClick={() => setOpen(true)} className="flex items-center gap-1 rounded-full bg-slate-900 px-3 py-2 text-xs text-green-300 shadow-lg"><Terminal className="h-4 w-4" aria-hidden /> Dev outbox ({rows.length})</button>
      )}
    </div>
  );
}
