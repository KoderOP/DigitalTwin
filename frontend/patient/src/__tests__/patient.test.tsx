import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import i18n from "@shared/i18n";
import { ConsentFlow, InviteFlow, LangPicker } from "../screens/Onboarding";
import { QuickLog } from "../screens/QuickLog";
import { TryIt } from "../screens/TryIt";
import type { PendingView } from "../types";
import { FoodPatterns } from "../screens/FoodPatterns";
import { DemoAccounts } from "../screens/DemoAccounts";

type Call = { url: string; body: unknown };
let calls: Call[] = [];

function mockFetch(routes: Record<string, unknown>) {
  calls = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null });
    const key = Object.keys(routes).find((k) => url.includes(k));
    return new Response(JSON.stringify(key ? routes[key] : {}), { status: 200, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
}

beforeEach(async () => { await i18n.changeLanguage("en"); });

describe("onboarding", () => {
  it("invite -> welcome -> OTP -> verified token", async () => {
    mockFetch({
      "/invite/open": { doctor: { name: "Dr. Asha Mehta", title: "Dr. Mehta" }, language: "en", dev_mode: true, otp_ttl_min: 5 },
      "/dev/otp": { message: "[Demo SMS] Your diabetes twin code is 123456." },
      "/invite/verify": { token: "PATIENT-TOKEN", language: "en" },
    });
    const onVerified = vi.fn();
    render(<InviteFlow invite="INV" onVerified={onVerified} />);
    expect(await screen.findByText(/Dr. Asha Mehta has set up this app/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Next"));
    fireEvent.click(screen.getByText("Demo: show my code"));
    expect(await screen.findByTestId("demo-sms")).toHaveTextContent("123456");
    const verify = screen.getByText("Verify").closest("button")!;
    expect(verify).toBeDisabled();
    fireEvent.change(screen.getByLabelText("6-digit code"), { target: { value: "12a3456" } });
    expect(verify).not.toBeDisabled();
    fireEvent.click(verify);
    await waitFor(() => expect(onVerified).toHaveBeenCalledWith("PATIENT-TOKEN"));
    const v = calls.find((c) => c.url.includes("/invite/verify"))!;
    expect(v.body).toMatchObject({ token: "INV", otp: "123456" });
    expect((v.body as { device_id: string }).device_id.length).toBeGreaterThan(8);
  });

  it("consent -> language -> tour -> simulated wearable -> start", async () => {
    const view: PendingView = { state: "CONSENT_PENDING", language: "en", doctor: { id: "d", name: "Dr. Asha Mehta", title: "Dr. Mehta" },
      consent_version: "1.0", features: { quick_log: true, try_it: true, progress: true, caregiver: true }, caregiver_allowed: true };
    const onAccept = vi.fn(async () => undefined);
    render(<ConsentFlow view={view} onAccept={onAccept} />);
    expect(screen.getByText(/synthetic/i)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/family member/));
    fireEvent.click(screen.getByText("I agree"));
    fireEvent.click(screen.getByText("हिन्दी"));
    expect(i18n.language).toBe("hi");
    fireEvent.click(screen.getByText("आगे"));
    for (let k = 0; k < 3; k++) fireEvent.click(screen.getByText("आगे"));
    const start = screen.getByText("शुरू करें").closest("button")!;
    expect(start).toBeDisabled(); // must connect the (simulated) wearable first
    fireEvent.click(screen.getByText("जोड़ें (सिम्युलेटेड)"));
    fireEvent.click(start);
    await waitFor(() => expect(onAccept).toHaveBeenCalledWith("hi", { share_logs: true, caregiver: true }));
  });
});

describe("language switching", () => {
  it("switches UI language between English, Hindi and Tamil", async () => {
    render(<LangPicker />);
    fireEvent.click(screen.getByText("தமிழ்"));
    expect(i18n.language).toBe("ta");
    expect(i18n.t("nav.home")).toBe("முகப்பு");
    fireEvent.click(screen.getByText("हिन्दी"));
    expect(i18n.t("nav.home")).toBe("होम");
    expect(screen.getByText("हिन्दी").closest("button")).toHaveAttribute("aria-pressed", "true");
  });
});

describe("Quick Log", () => {
  it("logs an Indian meal preset with portion and time-to-log", async () => {
    mockFetch({ "/me/logs": { ok: true, kind: "meal" } });
    const onLogged = vi.fn();
    render(<QuickLog token="T" onLogged={onLogged} />);
    fireEvent.click(screen.getByText("Poha"));
    fireEvent.click(screen.getByText("Large"));
    await act(async () => { fireEvent.click(screen.getByText("Save")); });
    expect(await screen.findByRole("status")).toHaveTextContent(/Saved/);
    const c = calls.find((x) => x.url.includes("/me/logs"))!;
    expect(c.body).toMatchObject({ kind: "meal", food: "poha", portion: "large" });
    expect(typeof (c.body as { duration_ms: number }).duration_ms).toBe("number");
    expect(onLogged).toHaveBeenCalled();
  });

  it("one-tap walk and symptom report with first-aid response", async () => {
    mockFetch({ "/me/logs": { ok: true, safety: { first_aid: { title: "Low sugar: what to do now", steps: ["Eat 15 g sugar"], emergency: "Call 108", contact: "Tell your doctor" } } } });
    render(<QuickLog token="T" />);
    await act(async () => { fireEvent.click(screen.getByText("15 min walk")); });
    expect(calls.at(-1)!.body).toMatchObject({ kind: "exercise", minutes: 15 });
    fireEvent.click(screen.getByText("Dizzy"));
    await act(async () => { fireEvent.click(screen.getByText("Save")); });
    expect(calls.at(-1)!.body).toMatchObject({ kind: "symptom", symptoms: ["dizziness"] });
    expect(await screen.findByText("Low sugar: what to do now")).toBeInTheDocument();
    expect(screen.getAllByText(/Call 108/).length).toBeGreaterThanOrEqual(2); // guidance text + tap-to-call button
    expect(screen.getByRole("link", { name: /Call 108/ })).toHaveAttribute("href", "tel:108");
  });
});

describe("food patterns and demo accounts", () => {
  it("shows foods to watch, symptom links and the consumption diary", () => {
    const f = {
      foods: [
        { key: "biryani", label: "Biryani", n: 3, mean_rise: 140, mean_peak: 262, pct_above: 100, mean_carbs: 95, minutes_above: 80, relative_to_usual: 2.1, flag: "watch" as const, confidence: "medium" as const, text: "After Biryani, your sugar rose about 140 mg/dL", based_on: "based on 3 meals" },
        { key: "roti_sabzi", label: "Roti-sabzi", n: 6, mean_rise: 42, mean_peak: 162, pct_above: 0, mean_carbs: 63, minutes_above: 0, relative_to_usual: 0.7, flag: "ok" as const, confidence: "high" as const, text: "", based_on: "based on 6 meals" },
      ],
      patterns: [{ key: "late_dinner", text: "Late dinners peaked about 60 mg/dL higher.", n: 6 }],
      symptom_links: [{ food: "biryani", label: "Biryani", symptom: "thirst", n: 2, glucose_at_symptom: 250, pattern: true, text: "Thirsty was reported after Biryani 2 time(s)." }],
      diary: [{ date: "2026-02-18", total_carbs: 220, meals: 3, late_meals: 1, sweets: 0, spikes_after_meals: 1,
        items: [{ time: "21:30", key: "biryani", label: "Biryani", carbs: 95, peak: 260, went_above: true, watch: true }] }],
      usual_rise: 65, meals_analysed: 9, meals_logged: 10, high: 180, tip: "Try a smaller portion", method: "Measured from your own sensor",
    };
    render(<FoodPatterns f={f} />);
    expect(screen.getByTestId("food-watch")).toHaveTextContent("Biryani");
    expect(screen.getByText(/Roti-sabzi/)).toBeInTheDocument();
    expect(screen.getByTestId("food-symptoms")).toHaveTextContent("Thirsty was reported after Biryani");
    expect(screen.getByText("Late dinners peaked about 60 mg/dL higher.")).toBeInTheDocument();
  });

  it("logs into a demo account with one tap", async () => {
    mockFetch({
      "/demo/accounts": [{ id: "demo1", label: "Demo patient 1 · English · standard plan", language: "en", patient_id: "TWN-AAAAAA", doctor: "Dr. Asha Mehta", state: "ACTIVE" }],
      "/demo/login": { token: "DEMO-TOKEN", patient_id: "TWN-AAAAAA", language: "en" },
    });
    const onLogin = vi.fn();
    render(<DemoAccounts fallback="no accounts" onLogin={onLogin} />);
    fireEvent.click(await screen.findByText("Demo patient 1 · English · standard plan"));
    await waitFor(() => expect(onLogin).toHaveBeenCalledWith("DEMO-TOKEN", "en"));
    expect(calls.find((c) => c.url.includes("/demo/login"))!.body).toMatchObject({ account: "demo1" });
  });
});

describe("Try It", () => {
  it("runs a plain-language what-if and shows the estimate", async () => {
    mockFetch({ "/me/tryit": { preset: "walk15", question: "What if I walk 15 minutes now?", times: ["2026-02-18T18:00:00", "2026-02-18T18:05:00"],
      before: [180, 200], after: [178, 185], delta_peak: 15, result: "Your estimated peak is 15 mg/dL lower.", note: "This is an estimate.", target: { low: 70, high: 180 } } });
    render(<TryIt token="T" />);
    await act(async () => { fireEvent.click(screen.getByText("What if I walk 15 minutes now?")); });
    expect(await screen.findByTestId("tryit-result")).toHaveTextContent("15 mg/dL lower");
    expect(screen.getByText("This is an estimate.")).toBeInTheDocument();
    expect(calls.at(-1)!.body).toEqual({ preset: "walk15" });
  });
});
