import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` serves the app on :5173 and forwards API and live-feed calls to the backend on :8010.
// `npm run build` writes web/dist, which the backend serves at http://127.0.0.1:8010/.
const backend = "http://127.0.0.1:8010";
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": backend, "/health": backend, "/ws": { target: backend, ws: true } } },
});
