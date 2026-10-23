import "@testing-library/jest-dom/vitest";
import "./i18n";

// Recharts' ResponsiveContainer needs ResizeObserver in jsdom
class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as unknown as { ResizeObserver: typeof RO }).ResizeObserver = RO;
