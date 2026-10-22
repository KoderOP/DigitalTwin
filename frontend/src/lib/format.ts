import type { Level, Summary } from "../types";

export const COLORS = {
  green: "#009E73",
  amber: "#E69F00",
  red: "#D55E00",
  high: "#CC79A7",
  blue: "#0072B2",
  sky: "#56B4E9",
  yellow: "#F0E442",
  grey: "#999999",
};

export const LEVEL_META: Record<Level, { label: string; color: string; text: string; description: string }> = {
  GREEN: { label: "GREEN", color: COLORS.green, text: "Low risk", description: "No spike expected in the next 2 h" },
  AMBER: { label: "AMBER", color: COLORS.amber, text: "Watch", description: "Possible spike > 180 mg/dL within 2 h" },
  RED: { label: "RED", color: COLORS.red, text: "Act", description: "Spike > 180 mg/dL likely within 2 h" },
  HIGH: { label: "HIGH NOW", color: COLORS.high, text: "Above 180", description: "Glucose is already above 180 mg/dL" },
};

export const TREND_ARROW: Record<Summary["trend"], { arrow: string; label: string }> = {
  up_fast: { arrow: "⇈", label: "rising fast" },
  up: { arrow: "↑", label: "rising" },
  flat: { arrow: "→", label: "stable" },
  down: { arrow: "↓", label: "falling" },
  down_fast: { arrow: "⇊", label: "falling fast" },
};

export const SLEEP_STAGE = ["Awake", "Light", "Deep", "REM"];

export const fmtTime = (iso: string | number) =>
  new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false });

export const fmtDateTime = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", { weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });

export const pct = (x: number | null | undefined, d = 0) => (x == null || Number.isNaN(x) ? "–" : `${(x * 100).toFixed(d)}%`);

export const num = (x: number | null | undefined, d = 0) => (x == null || Number.isNaN(x) ? "–" : x.toFixed(d));

export const ms = (iso: string) => new Date(iso).getTime();

export function countdownText(minutes: number | null | undefined, level: Level): string {
  if (level === "HIGH") return "Glucose already above 180 mg/dL";
  if (minutes == null) return level === "GREEN" ? "No spike forecast within 2 h" : "Spike possible within 2 h";
  if (minutes <= 5) return "Spike imminent (< 5 min)";
  return `Predicted spike in ~${minutes} min`;
}
