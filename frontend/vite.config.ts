import { defineConfig } from "vite";

// COI=1 serves the app cross-origin isolated (COOP/COEP), which changes browser timer precision.
// P1 measures timing with and without it (SPEC 4.1, 4.11).
const crossOriginIsolated = process.env.COI === "1";

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
