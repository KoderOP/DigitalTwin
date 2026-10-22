import { render, screen } from "@testing-library/react";
import { LevelBadge } from "../components/LevelBadge";
import { sortAndFilter } from "../components/CohortList";
import { buildScenario, PRESETS, WhatIfPanel } from "../components/WhatIfPanel";
import { countdownText } from "../lib/format";
import type { Summary } from "../types";

const row = (id: string, level: Summary["level"], risk: number, g = 120): Summary => ({
  patient_id: id, age: 50, sex: "M", region: "urban", hba1c: 8, bmi_band_sa: "obese", insulin: false, cgm: g, g_now: g,
  trend: "flat", risk, level, minutes_to_spike: null, nocturnal_flag: null, hypo_risk: null, active_alerts: 0, data_quality: "good", ts: null,
});

describe("LevelBadge", () => {
  it("conveys level with text and an accessible description, not colour alone", () => {
    render(<LevelBadge level="RED" />);
    const el = screen.getByRole("status");
    expect(el).toHaveTextContent("RED");
    expect(el.getAttribute("aria-label")).toMatch(/likely within 2 h/);
    expect(el.querySelector("svg")).not.toBeNull();
  });
});

describe("cohort sorting/filtering", () => {
  const rows = [row("TWN-B", "GREEN", 0.1), row("TWN-A", "RED", 0.9), row("TWN-C", "AMBER", 0.5), row("TWN-D", "AMBER", 0.6)];
  it("sorts by risk level then probability", () => {
    expect(sortAndFilter(rows, "", "ALL", "risk").map((r) => r.patient_id)).toEqual(["TWN-A", "TWN-D", "TWN-C", "TWN-B"]);
  });
  it("filters by level and search", () => {
    expect(sortAndFilter(rows, "", "AMBER", "risk")).toHaveLength(2);
    expect(sortAndFilter(rows, "twn-c", "ALL", "risk").map((r) => r.patient_id)).toEqual(["TWN-C"]);
  });
});

describe("what-if", () => {
  it("builds a combined scenario request", () => {
    const s = buildScenario({ meal: true, carbs: 60, gi: "high", mealAt: "21:00", ex: true, exMin: 20, intensity: "moderate", exIn: 15,
      med: false, drug: "metformin", dose: 500, sleep: false, hours: 7 });
    expect(s.interventions).toEqual([
      { type: "meal", carbs: 60, gi: "high", at: "21:00" },
      { type: "exercise", minutes: 20, intensity: "moderate", in_min: 15 },
    ]);
    expect(s.name).toContain("60 g");
  });
  it("offers the presets required by the brief", () => {
    const labels = PRESETS.map((p) => p.label).join("|");
    expect(labels).toMatch(/Walk 20 min/);
    expect(labels).toMatch(/Metformin/);
    expect(labels).toMatch(/19:00 vs 21:00/);
    expect(labels).toMatch(/5 h vs 8 h/);
    render(<WhatIfPanel patientId="TWN-X" />);
    expect(screen.getByText("Sleep 5 h vs 8 h")).toBeInTheDocument();
  });
});

describe("countdown text", () => {
  it("formats predicted spike timing", () => {
    expect(countdownText(45, "AMBER")).toBe("Predicted spike in ~45 min");
    expect(countdownText(null, "GREEN")).toMatch(/No spike/);
    expect(countdownText(10, "HIGH")).toMatch(/already above/);
  });
});
