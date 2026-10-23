import { render, screen } from "@testing-library/react";
import detailJson from "./fixtures/detail.json";
import type { Detail } from "../types";
import { CgmChart, timeDomain } from "../components/CgmChart";
import { RiskGauge, RiskHistory } from "../components/RiskGauge";
import { SignalsPanel } from "../components/SignalsPanel";
import { ExplainPanel } from "../components/ExplainPanel";
import { MetricsPanel } from "../components/MetricsPanel";
import { PatientHeader } from "../components/PatientHeader";
import { ClinicianPanel } from "../components/ClinicianPanel";

// A real payload captured from the backend (synthetic patient): renders every twin-view panel.
const d = detailJson as unknown as Detail;

beforeEach(() => {
  globalThis.fetch = vi.fn(async () => new Response("[]", { status: 200 })) as unknown as typeof fetch;
});

describe("twin view renders a real backend payload", () => {
  const dom = timeDomain(d);
  it("charts and gauge", () => {
    render(<><CgmChart d={d} dom={dom} /><RiskHistory d={d} dom={dom} /><SignalsPanel d={d} dom={dom} /></>);
    expect(screen.getByRole("img", { name: /Continuous glucose chart/ })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Sleep stage timeline/ })).toBeInTheDocument();
  });
  it("risk gauge, explanation, metrics, header, actions", () => {
    render(
      <>
        <RiskGauge p={d.prediction!} />
        <ExplainPanel p={d.prediction!} />
        <MetricsPanel d={d} />
        <PatientHeader d={d} />
        <ClinicianPanel d={d} onChanged={() => undefined} />
      </>,
    );
    expect(screen.getByText(d.header.patient_id)).toBeInTheDocument();
    expect(screen.getAllByText(/Time in ranges/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Audit trail/)).toBeInTheDocument();
    expect(d.prediction!.explanation!.length).toBeGreaterThan(0);
  });
});
