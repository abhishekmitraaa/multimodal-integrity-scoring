import { defineConfig, devices } from "@playwright/test";

const python = process.platform === "win32" ? "..\\.venv\\Scripts\\python.exe" : "../.venv/bin/python";

// Port 5173 serves the app normally; 5174 serves it cross-origin isolated (COOP/COEP) so the
// timing measurements can compare both (SPEC 4.1, 4.11).
export default defineConfig({
  testDir: "tests",
  timeout: 120_000,
  workers: 1,
  reporter: [["list"]],
  // BASE_URL=http://127.0.0.1:5174 runs the suite cross-origin isolated.
  use: { baseURL: process.env.BASE_URL ?? "http://127.0.0.1:5173", trace: "retain-on-failure" },
  webServer: [
    {
      command: `${python} ../backend/scripts/serve_e2e.py`,
      url: "http://127.0.0.1:8000/api/health",
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: "pipe",
    },
    { command: "npx vite --port 5173 --strictPort", url: "http://127.0.0.1:5173", timeout: 60_000, reuseExistingServer: false },
    {
      command: "npx vite --port 5174 --strictPort",
      url: "http://127.0.0.1:5174",
      env: { COI: "1" },
      timeout: 60_000,
      reuseExistingServer: false,
    },
  ],
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], permissions: ["clipboard-read", "clipboard-write"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    // Not devices["Desktop Safari"]: its macOS user agent makes Monaco bind Cmd shortcuts while
    // Playwright on Windows sends Ctrl. WebKit on Windows is only a proxy for Safari; real Safari
    // must be checked on a Mac.
    { name: "webkit", use: { browserName: "webkit", viewport: { width: 1280, height: 720 } } },
  ],
});
