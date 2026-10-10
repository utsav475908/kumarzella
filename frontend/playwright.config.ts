import { defineConfig } from "@playwright/test";

/** Runs against an already running stack (API on :8000, Vite on :5173). See README "End-to-end tests". */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    launchOptions: process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {},
    screenshot: "only-on-failure",
  },
  reporter: [["list"]],
});
