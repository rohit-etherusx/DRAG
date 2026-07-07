import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// In dev, the app runs on Vite's server and proxies engine calls to the API
// (default 127.0.0.1:8000), so there is no CORS friction and no hard-coded URL.
// In production, `npm run build` emits ./dist which the FastAPI app serves at /,
// making calls same-origin. Override the dev target with VITE_API_TARGET.
const API_TARGET = process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/health": API_TARGET,
      "/research": API_TARGET,
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
