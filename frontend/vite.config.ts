import { defineConfig } from "vite";

// The app is served cross-origin isolated (COOP/COEP) by default (D-021): finer timers, and the same
// setting for every session. COI=0 serves it without isolation, only to measure the difference.
const crossOriginIsolated = process.env.COI !== "0";

export default defineConfig({
  server: {
    host: "127.0.0.1",
    headers: crossOriginIsolated
      ? { "Cross-Origin-Opener-Policy": "same-origin", "Cross-Origin-Embedder-Policy": "require-corp" }
      : {},
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
  worker: { format: "es" },
});
