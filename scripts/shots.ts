/*
 * shots: one command that screenshots every representative screen (docs/ui-profile.md) at the three
 * supported viewports, three themes and two languages, into
 *
 *   shots/<label>/<screen>--<viewport>--<theme>--<lang>.png
 *
 * so the UI can be reviewed (and compared) before and after a change.
 *
 *   make shots LABEL=before            (BASE_URL defaults to http://localhost:$FRONTEND_PORT)
 *   BASE_URL=http://localhost:5400 node scripts/shots.ts before     (from e2e/, which has playwright)
 *
 * The app must already be running against the demo database (see docs/runbooks/demo.md):
 *   DB_NAME=demo_hospital BACKEND_PORT=8400 FRONTEND_PORT=5400 make dev
 * Demo accounts and password come from backend/apps/core/demo/catalog.py (DEMO_PASSWORD).
 *
 * Reproducibility: reduced motion on, Date.now fixed to 10:00 of the current day in
 * Africa/Khartoum, a fixed timezone and locale per context. The data is the seeded demo month;
 * pick the same records every run (first match of a stable query), so two runs on the same DB
 * differ only if the UI does.
 *
 * Narrow the run (comma lists): ONLY=dashboard,cashier THEMES=light LANGS=ar VIEWPORTS=375
 * Runs on Node >= 22.6 (type stripping): no build step.
 */
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
// Playwright lives in e2e/node_modules (pnpm does not hoist it to the repo root).
const requireE2e = createRequire(path.join(root, "e2e", "package.json"));
const { chromium } = requireE2e("@playwright/test");

type Theme = "light" | "dark" | "warm";
type Lang = "ar" | "en";
type Role = "manager" | "cashier" | "doctor" | "pharmacist" | "portal";

const BASE_URL = process.env.BASE_URL ?? `http://localhost:${process.env.FRONTEND_PORT ?? "5173"}`;
const LABEL = process.argv[2] ?? "current";
const PASSWORD = process.env.DEMO_PASSWORD ?? "Demo-Pass-2026";
const OUT = path.join(root, "shots", LABEL);

const ALL_VIEWPORTS = [
  { name: "375", width: 375, height: 812 },
  { name: "768", width: 768, height: 1024 },
  { name: "1280", width: 1280, height: 800 },
];
const ALL_THEMES: Theme[] = ["light", "dark", "warm"];
const ALL_LANGS: Lang[] = ["ar", "en"];

function pick<T>(all: T[], env: string | undefined, key: (x: T) => string): T[] {
  if (!env) return all;
  const wanted = new Set(env.split(",").map((s) => s.trim()));
  return all.filter((x) => wanted.has(key(x)));
}
const VIEWPORTS = pick(ALL_VIEWPORTS, process.env.VIEWPORTS, (v) => v.name);
const THEMES = pick(ALL_THEMES, process.env.THEMES, (t) => t);
const LANGS = pick(ALL_LANGS, process.env.LANGS, (l) => l);
const ONLY = process.env.ONLY?.split(",").map((s) => s.trim());

/** Facts looked up once per role through the API (stable: first match of a stable query). */
interface Facts {
  cashierVisit?: number;
  doctorVisit?: number;
  portal?: { fileNo: string; phone: string; code: string };
}

interface Screen {
  id: string;
  role: Role;
  /** Path (and query) to open. */
  path: (facts: Facts) => string | null;
  /** A selector that proves the screen is rendered with its data. */
  ready: string;
  /** Extra steps after load (open a dialog...). */
  setup?: (page: any) => Promise<void>;
  /** Intercepts installed before navigation (loading / error states). */
  intercept?: (page: any) => Promise<void>;
  /** States are captured on a reduced matrix (light theme only) to keep the run short. */
  stateOnly?: boolean;
}

const SCREENS: Screen[] = [
  {
    id: "dashboard",
    role: "manager",
    path: () => "/",
    ready: '[data-testid="manager-dashboard"] [data-slot="kpi-card"] [data-slot="money"]',
  },
  {
    id: "dashboard-loading",
    role: "manager",
    path: () => "/",
    ready: '[data-testid="manager-dashboard"]',
    stateOnly: true,
    intercept: async (page) => {
      await page.route("**/api/reports/dashboard", () => {
        // Never answered: the skeletons stay.
      });
    },
  },
  {
    id: "dashboard-error",
    role: "manager",
    path: () => "/",
    ready: '[data-slot="alert-card"]',
    stateOnly: true,
    intercept: async (page) => {
      await page.route("**/api/reports/dashboard", (route: any) =>
        route.fulfill({ status: 500, contentType: "application/json", body: '{"code":"internal_error"}' }),
      );
    },
  },
  {
    id: "cashier-empty",
    role: "cashier",
    path: () => "/cashier",
    ready: '[data-slot="empty-state"]',
  },
  {
    id: "cashier-invoice",
    role: "cashier",
    path: (f) => (f.cashierVisit ? `/cashier?visit=${f.cashierVisit}` : null),
    ready: '[data-testid="invoice-line"]',
  },
  {
    id: "visit",
    role: "doctor",
    path: (f) => (f.doctorVisit ? `/clinic/visits/${f.doctorVisit}` : null),
    ready: '[data-slot="patient-card"]',
  },
  {
    id: "pharmacy-queue",
    role: "pharmacist",
    path: () => "/pharmacy",
    ready: '[data-testid="queue-visit"]',
  },
  {
    id: "pharmacy-dispense",
    role: "pharmacist",
    path: () => "/pharmacy",
    ready: '[data-testid="queue-visit"]',
    setup: async (page) => {
      await page.locator('[data-testid="queue-dispense"]').first().click();
      await page.locator('[role="dialog"]').waitFor();
    },
  },
  {
    id: "pharmacy-empty",
    role: "pharmacist",
    path: () => "/pharmacy?q=zzzz-no-such-patient",
    ready: '[data-testid="queue-scan"]',
    stateOnly: true,
    setup: async (page) => {
      await page.locator('[data-testid="queue-scan"]').fill("zzzz-no-such-patient");
      await page.locator('[data-slot="empty-state"]').waitFor();
    },
  },
  {
    id: "portal-home",
    role: "portal",
    path: () => "/portal/home",
    ready: "main h1",
  },
];

// ------------------------------------------------------------------------------------ plumbing

const USERNAME: Record<Exclude<Role, "portal">, string> = {
  manager: "manager",
  cashier: "cashier",
  doctor: "dr.hamid",
  pharmacist: "pharmacist",
};

async function csrf(ctx: any): Promise<Record<string, string>> {
  await ctx.request.get("/api/auth/csrf");
  const cookie = (await ctx.cookies(BASE_URL)).find((c: any) => c.name === "csrftoken");
  if (!cookie) throw new Error("no csrftoken cookie from /api/auth/csrf");
  return { "X-CSRFToken": cookie.value };
}

async function staffLogin(ctx: any, username: string): Promise<void> {
  const response = await ctx.request.post("/api/auth/login", {
    headers: await csrf(ctx),
    data: { username, password: PASSWORD },
  });
  if (response.status() !== 200) throw new Error(`login ${username}: ${response.status()} ${await response.text()}`);
}

async function json(ctx: any, url: string): Promise<any> {
  const response = await ctx.request.get(url);
  if (!response.ok()) throw new Error(`GET ${url}: ${response.status()} ${await response.text()}`);
  return response.json();
}

/** Looks up the demo records the screens need. Adjust here if the demo dataset changes. */
async function findFacts(browser: any): Promise<Facts> {
  const facts: Facts = {};

  const cashier = await browser.newContext({ baseURL: BASE_URL });
  await staffLogin(cashier, USERNAME.cashier);
  // A visit with invoice lines: the first visit among the pharmacy queue's paid ones is a good
  // candidate; fall back to a cashier lookup by a common letter.
  const lookup = await json(cashier, "/api/billing/lookup?q=a");
  const visits: any[] = lookup.visits ?? lookup.results ?? [];
  for (const v of visits.slice(0, 12)) {
    const billing = await json(cashier, `/api/billing/visits/${v.visit_id ?? v.id}`);
    if ((billing.invoices ?? []).some((inv: any) => (inv.lines ?? []).length >= 2)) {
      facts.cashierVisit = v.visit_id ?? v.id;
      break;
    }
  }
  await cashier.close();

  const doctor = await browser.newContext({ baseURL: BASE_URL });
  await staffLogin(doctor, USERNAME.doctor);
  const worklist = await json(doctor, "/api/clinical/worklist");
  const entries: any[] = worklist.entries ?? worklist.items ?? worklist ?? [];
  const first = entries.find((e: any) => e.visit_id ?? e.visit?.id);
  if (first) facts.doctorVisit = first.visit_id ?? first.visit.id;
  await doctor.close();

  // The portal needs a printed access code: issue one for a demo patient as the receptionist.
  const reception = await browser.newContext({ baseURL: BASE_URL });
  await staffLogin(reception, "reception");
  const found = await json(reception, "/api/patients?q=a&limit=1");
  const patient = (found.items ?? found.results ?? found)[0];
  if (patient) {
    const issued = await reception.request.post(`/api/portal/patients/${patient.id}/access-codes`, {
      headers: await csrf(reception),
      data: {},
    });
    if (issued.ok()) {
      const body = await issued.json();
      facts.portal = { fileNo: patient.file_no, phone: patient.phone, code: body.code };
    }
  }
  await reception.close();
  return facts;
}

async function loginRole(browser: any, role: Role, facts: Facts): Promise<any | null> {
  const ctx = await browser.newContext({ baseURL: BASE_URL });
  if (role === "portal") {
    if (!facts.portal) {
      await ctx.close();
      return null;
    }
    const response = await ctx.request.post("/api/portal/session", {
      headers: await csrf(ctx),
      data: { file_no: facts.portal.fileNo, phone: facts.portal.phone, code: facts.portal.code },
    });
    if (response.status() !== 200) {
      console.warn(`portal sign-in failed: ${response.status()}`);
      await ctx.close();
      return null;
    }
  } else {
    await staffLogin(ctx, USERNAME[role]);
  }
  const state = await ctx.storageState();
  await ctx.close();
  return state;
}

async function main(): Promise<void> {
  mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const facts = await findFacts(browser);
  console.log("facts:", JSON.stringify({ ...facts, portal: facts.portal ? { ...facts.portal, code: "***" } : undefined }));

  const screens = SCREENS.filter((s) => !ONLY || ONLY.some((o) => s.id === o || s.id.startsWith(`${o}-`)));
  const roles = [...new Set(screens.map((s) => s.role))];
  const skipped: string[] = [];
  let taken = 0;

  for (const role of roles) {
    const state = await loginRole(browser, role, facts);
    if (!state) {
      skipped.push(`${role}: could not sign in`);
      continue;
    }
    for (const theme of THEMES) {
      for (const lang of LANGS) {
        const ctx = await browser.newContext({
          baseURL: BASE_URL,
          storageState: state,
          viewport: { width: 1280, height: 800 },
          colorScheme: theme === "dark" ? "dark" : "light",
          locale: lang === "ar" ? "ar-SD" : "en-GB",
          timezoneId: "Africa/Khartoum",
          reducedMotion: "reduce",
        });
        await ctx.addInitScript(
          ({ theme: th, lang: lg }: { theme: string; lang: string }) => {
            try {
              window.localStorage.setItem("hs.theme", th);
              window.localStorage.setItem("hs.lang", lg);
            } catch {
              // storage unavailable: the server profile below still applies for staff
            }
          },
          { theme, lang },
        );
        if (role !== "portal") {
          // Staff preferences live on the server profile and win over the local cache.
          const patched = await ctx.request.patch("/api/auth/me/preferences", {
            headers: await csrf(ctx),
            data: { theme, language: lang },
          });
          if (!patched.ok()) console.warn(`preferences ${role}: ${patched.status()}`);
        }
        const now = new Date();
        now.setHours(10, 0, 0, 0);

        for (const screen of screens.filter((s) => s.role === role)) {
          if (screen.stateOnly && theme !== "light") continue;
          const target = screen.path(facts);
          if (!target) {
            skipped.push(`${screen.id}: no demo record found`);
            continue;
          }
          for (const vp of VIEWPORTS) {
            const page = await ctx.newPage();
            try {
              await page.clock.setFixedTime(now);
              await page.setViewportSize({ width: vp.width, height: vp.height });
              await screen.intercept?.(page);
              await page.goto(target, { waitUntil: "load" });
              await page.locator(screen.ready).first().waitFor({ timeout: 30_000 });
              await screen.setup?.(page);
              await page.evaluate(() => document.fonts.ready);
              await page.waitForTimeout(400);
              await page.screenshot({
                path: path.join(OUT, `${screen.id}--${vp.name}--${theme}--${lang}.png`),
                fullPage: true,
              });
              taken += 1;
            } catch (error) {
              skipped.push(`${screen.id}--${vp.name}--${theme}--${lang}: ${(error as Error).message.split("\n")[0]}`);
            } finally {
              await page.close();
            }
          }
        }
        await ctx.close();
      }
    }
  }

  await browser.close();
  console.log(`shots: ${taken} screenshots in ${path.relative(root, OUT)}`);
  if (skipped.length > 0) console.log(`shots: skipped or failed (${skipped.length}):\n  ${skipped.join("\n  ")}`);
}

await main();
