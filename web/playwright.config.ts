import { defineConfig, devices } from "@playwright/test";

const PORT = 8765;
const python = process.env.WA_PYTHON ?? "python3";

export default defineConfig({
  testDir: "e2e",
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "off",
    launchOptions: process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {},
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1366, height: 800 } } }],
  webServer: {
    command: `${python} ../tests/e2e_server.py ${PORT} ./dist`,
    url: `http://localhost:${PORT}/healthz`,
    timeout: 240_000,
    reuseExistingServer: false,
  },
});
