/// <reference types="vitest" />
import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// One multi-page build: doctor dashboard (served at /) and patient PWA (served at /patient/).
// Dev server: http://localhost:5173/doctor/ and http://localhost:5173/patient/ (API proxied to :8000).
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@shared": resolve(__dirname, "shared") } },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
  build: {
    outDir: "dist",
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      input: { doctor: resolve(__dirname, "doctor/index.html"), patient: resolve(__dirname, "patient/index.html") },
    },
  },
  test: { environment: "jsdom", globals: true, setupFiles: ["./shared/setupTests.ts"] },
});
