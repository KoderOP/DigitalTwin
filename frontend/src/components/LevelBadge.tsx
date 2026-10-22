import { AlertOctagon, AlertTriangle, ArrowUpCircle, CheckCircle2 } from "lucide-react";
import type { Level } from "../types";
import { LEVEL_META } from "../lib/format";

const ICONS = { GREEN: CheckCircle2, AMBER: AlertTriangle, RED: AlertOctagon, HIGH: ArrowUpCircle };

/** Risk badge: colour + distinct icon shape + text, so it never relies on colour alone. */
export function LevelBadge({ level, size = "sm" }: { level: Level; size?: "sm" | "lg" }) {
  const m = LEVEL_META[level];
  const Icon = ICONS[level];
  const big = size === "lg";
  return (
    <span
      role="status"
      aria-label={`${m.label}: ${m.description}`}
      title={m.description}
      className={`inline-flex items-center gap-1 rounded-full font-semibold text-white ${big ? "px-3 py-1 text-sm" : "px-2 py-0.5 text-[11px]"}`}
      style={{ backgroundColor: m.color }}
    >
      <Icon aria-hidden className={big ? "h-4 w-4" : "h-3 w-3"} />
      {m.label}
    </span>
  );
}
