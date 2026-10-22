/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Okabe-Ito colour-blind-safe palette; levels are never conveyed by colour alone
        risk: { green: "#009E73", amber: "#E69F00", red: "#D55E00", high: "#CC79A7" },
        brand: { DEFAULT: "#0072B2", light: "#56B4E9" },
      },
      fontFamily: { sans: ["Inter", "system-ui", "Segoe UI", "Roboto", "sans-serif"] },
    },
  },
  plugins: [],
};
