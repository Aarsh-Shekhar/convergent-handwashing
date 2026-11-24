// Browser tests run against the real backend serving the built app (web/dist) with a throwaway demo database.
// Run `npm run build` first; `npm run test:e2e` starts the backend, seeds the demo family and drives Chrome.
import { defineConfig } from "@playwright/test";
import { tmpdir } from "node:os";
import { join } from "node:path";

export const PORT = 8020;
export const TOKEN = "e2e-token-not-a-secret";
const db = join(tmpdir(), `scrubble-e2e-${process.pid}.db`);

export default defineConfig({
  testDir: "tests/e2e",
  workers: 1,               // one database, and the tests tell one story in order
  fullyParallel: false,
  retries: 0,
  timeout: 30_000,
  reporter: [["list"]],
  globalSetup: "./tests/e2e/seed.ts",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    channel: process.env.PW_CHANNEL ?? "chrome",
    viewport: { width: 390, height: 844 },
    timezoneId: process.env.E2E_TZ ?? "America/Chicago",
    trace: "retain-on-failure",
  },
  webServer: {
    command: `../.venv/bin/python -m convergent.cli backend --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/health`,
    reuseExistingServer: false,
    env: { CONVERGENT_API_TOKEN: TOKEN, CONVERGENT_DEMO_MODE: "true", CONVERGENT_DATABASE_URL: `sqlite:///${db}`, CONVERGENT_LOG_DIR: join(tmpdir(), "scrubble-e2e-logs") },
  },
});
