import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./index.css";

// Restore the saved theme before first paint (index.html defaults to dark).
try {
  const saved = localStorage.getItem("re-theme");
  if (saved) {
    document.documentElement.classList.toggle("dark", saved === "dark");
  }
} catch {
  /* storage unavailable — keep the default */
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
