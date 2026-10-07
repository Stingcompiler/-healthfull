/**
 * Runs once after both web servers are up, before any spec:
 *
 * 1. Warms the Vite dev server. The first visit to a page makes Vite
 *    pre-bundle dependencies and, when it finds new ones (the lazily loaded
 *    /design chunk), reload the page. Doing that here keeps the reload out of
 *    the specs, where it would look like a flaky render.
 * 2. Logs the e2e admin and pharmacist in through the API and saves their sessions to
 *    .auth/{admin,pharmacist}.json for specs that need a logged-in page.
 */
import { mkdirSync } from "node:fs";

import { chromium, request, type FullConfig } from "@playwright/test";

import { AUTH_DIR, BASE_URL } from "./env";
import { ADMIN_STATE, PHARMACIST_STATE } from "./fixtures/state";
import { apiLogin } from "./helpers/auth";

const WARM_PATHS = ["/login", "/portal", "/", "/design", "/administration/users"];

async function warmUp(): Promise<void> {
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext({ baseURL: BASE_URL, storageState: ADMIN_STATE });
    const page = await context.newPage();
    for (const path of WARM_PATHS) {
      // Twice: the second load must find every dependency already optimized.
      for (let i = 0; i < 2; i += 1) {
        await page.goto(path, { waitUntil: "networkidle", timeout: 120_000 });
      }
    }
    await context.close();
  } finally {
    await browser.close();
  }
}

export default async function globalSetup(_config: FullConfig): Promise<void> {
  mkdirSync(AUTH_DIR, { recursive: true });
  for (const [who, file] of [
    ["admin", ADMIN_STATE],
    ["pharmacist", PHARMACIST_STATE],
  ] as const) {
    const api = await request.newContext({ baseURL: BASE_URL });
    try {
      await apiLogin(api, who);
      await api.storageState({ path: file });
    } finally {
      await api.dispose();
    }
  }
  await warmUp();
}
