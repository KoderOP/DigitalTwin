import React from "react";
import ReactDOM from "react-dom/client";
import "@shared/i18n";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

// Installable PWA: offline shell via a small service worker (never caches API data).
if ("serviceWorker" in navigator && location.pathname.startsWith("/patient")) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/patient/sw.js", { scope: "/patient/" }).catch(() => undefined);
  });
}
