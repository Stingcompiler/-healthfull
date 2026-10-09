/**
 * Playwright config (ARCHITECTURE 6). Run through `make e2e` (scripts/e2e.sh),
 * which resets the e2e database, seeds it, exports the ports and E2E_DB_NAME used
 * below, and passes E2E_GREP as --grep. Running `pnpm test` here directly works
 * too when the e2e database already exists and is seeded.
 *
 * Both servers are started by Playwright and stopped when the run ends:
 *   backend   Django runserver --noreload on 127.0.0.1:$BACKEND_PORT, DB_NAME=e2e_hospital_<hash>
 *   frontend  Vite (`pnpm dev`) on 127.0.0.1:$FRONTEND_PORT, proxying /api and /admin to the backend
 * Their output goes to e2e/.logs/{backend,frontend}.log.
 */
import { mkdirSync } from "node:fs";
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

import {
  BACKEND_DIR,
  BACKEND_PORT,
  BACKEND_URL,
  BASE_URL,
  DB_NAME,
  FRONTEND_DIR,
  FRONTEND_PORT,
  LOGS_DIR,
} from "./env";

mkdirSync(LOGS_DIR, { recursive: true });

const CI = process.env.CI === "true" || process.env.CI === "1";
/** Reuse servers already listening on the ports (local debugging only; they must use DB_NAME). */
const REUSE = process.env.E2E_REUSE_SERVERS === "1";

const serverEnv: Record<string, string> = {
  ...(Object.fromEntries(Object.entries(process.env).filter(([, v]) => v !== undefined)) as Record<string, string>),
  DB_NAME,
  BACKEND_PORT: String(BACKEND_PORT),
  FRONTEND_PORT: String(FRONTEND_PORT),
  // seed_e2e and the dev-only conveniences need DEBUG; this is never a production server.
  DJANGO_DEBUG: "1",
};

function logTo(name: string): string {
  return `>> "${path.join(LOGS_DIR, `${name}.log`)}" 2>&1`;
}

export default defineConfig({
  testDir: "./tests",
  outputDir: "./test-results",
  globalSetup: "./global-setup.ts",
  // Specs share server-side state (the admin's saved preferences, seed users), so one worker.
  // Sharded CI runs split by test, not by file (serial-mode files stay together).
  // Workers stay at 1, so tests still run one at a time against the single dev server.
  fullyParallel: Boolean(process.env.E2E_SHARD),
  workers: 1,
  retries: 0,
  forbidOnly: CI,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  use: {
    baseURL: BASE_URL,
    ...devices["Desktop Chrome"],
    colorScheme: "light",
    timezoneId: "Africa/Khartoum",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium" }],
  webServer: [
    {
      name: "backend",
      command: `uv run python manage.py runserver 127.0.0.1:${String(BACKEND_PORT)} --noreload ${logTo("backend")}`,
      cwd: BACKEND_DIR,
      url: `${BACKEND_URL}/api/ops/health`,
      env: serverEnv,
      reuseExistingServer: REUSE,
      timeout: 120_000,
      gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
    },
    {
      name: "frontend",
      command: `pnpm dev ${logTo("frontend")}`,
      cwd: FRONTEND_DIR,
      url: `${BASE_URL}/login`,
      env: serverEnv,
      reuseExistingServer: REUSE,
      timeout: 120_000,
      gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
    },
  ],
});
