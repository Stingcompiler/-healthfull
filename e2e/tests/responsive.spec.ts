/**
 * Responsive matrix (ARCHITECTURE 5.3 and 6): every route x 3 viewports x
 * 3 themes x 2 languages. Each case loads the page fresh and checks that it
 * renders, <html> carries the right theme/lang/dir, there is no horizontal
 * page scroll, and nothing was logged at error level.
 *
 * Screenshots (artifacts/screens/<route>-<viewport>-<theme>-<lang>.png) only
 * for (ar, light), (en, dark) and (ar, warm).
 *
 * Filter with E2E_GREP, e.g. `make e2e E2E_GREP="@responsive.*design"`.
 */
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { FRONTEND_DIR } from "../env";
import { ADMIN_STATE, ANONYMOUS_STATE } from "../fixtures/state";
import {
  expectNoHorizontalScroll,
  expectPrefsApplied,
  LANGS,
  setPrefs,
  snap,
  THEMES,
  trackConsoleErrors,
  type Lang,
  type Theme,
} from "../helpers";
import { ROUTES } from "../routes";

const VIEWPORTS = [
  { label: "phone", width: 375, height: 812 },
  { label: "tablet", width: 768, height: 1024 },
  { label: "desktop", width: 1280, height: 800 },
] as const;

const SCREENSHOT_COMBOS: ReadonlySet<string> = new Set(["light/ar", "dark/en", "warm/ar"]);
const wantsScreenshot = (theme: Theme, lang: Lang) => SCREENSHOT_COMBOS.has(`${theme}/${lang}`);

for (const viewport of VIEWPORTS) {
  test.describe(`@responsive ${String(viewport.width)}x${String(viewport.height)}`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });

    for (const route of ROUTES) {
      test.describe(route.name, () => {
        test.use({ storageState: route.auth ? ADMIN_STATE : ANONYMOUS_STATE });

        for (const theme of THEMES) {
          for (const lang of LANGS) {
            test(`${theme} ${lang}`, async ({ page }) => {
              const logged = trackConsoleErrors(page, { allowAnonymousMe: !route.auth });
              await setPrefs(page, { theme, lang });

              await page.goto(route.path);
              await expect(route.ready(page)).toBeVisible();
              // Still on the route: no bounce to /login, no redirect elsewhere.
              expect(new URL(page.url()).pathname).toBe(route.path);
              await expectPrefsApplied(page, { theme, lang });
              await page.evaluate(() => document.fonts.ready.then(() => undefined));

              await expectNoHorizontalScroll(page);
              if (wantsScreenshot(theme, lang)) await snap(page, route.name);

              expect(logged.errors(), "console errors / page errors").toEqual([]);
            });
          }
        }
      });
    }
  });
}

/**
 * The phone tab bar has five cells (four modules + More). Which modules land there depends on
 * the user's permissions, so every short label (nav:short) in both languages must fit a cell
 * without an ellipsis, at 360px: the most common Android width, narrower than the 375 matrix.
 */
test.describe("@responsive phone tab bar", () => {
  test.use({ viewport: { width: 360, height: 800 }, storageState: ADMIN_STATE });

  for (const lang of LANGS) {
    test(`every short label fits at 360px (${lang})`, async ({ page }) => {
      const file = path.join(FRONTEND_DIR, "src", "i18n", "locales", lang, "nav.json");
      const nav = JSON.parse(readFileSync(file, "utf8")) as { short: Record<string, string>; shell: { more: string } };
      const labels = [...Object.values(nav.short), nav.shell.more];
      expect(labels.length).toBeGreaterThan(10);

      await setPrefs(page, { theme: "light", lang });
      await page.goto("/");
      const bar = page.locator('[data-slot="app-bottom-nav"]');
      await expect(bar).toBeVisible();
      await expectPrefsApplied(page, { theme: "light", lang });
      await page.evaluate(() => document.fonts.ready.then(() => undefined));

      // Measure each label in a real cell: same element, classes and font as the live label.
      const truncated = await bar.evaluate((nav, texts) => {
        const span = nav.querySelector<HTMLElement>("li a span");
        if (!span) throw new Error("no label in the bottom navigation");
        const original = span.textContent;
        const out: string[] = [];
        for (const text of texts) {
          span.textContent = text;
          if (span.scrollWidth > span.clientWidth) {
            out.push(`${text} (${String(span.scrollWidth)}px > ${String(span.clientWidth)}px)`);
          }
        }
        span.textContent = original;
        return out;
      }, labels);
      expect(truncated, `shorten these in frontend/src/i18n/locales/${lang}/nav.json "short"`).toEqual([]);
    });
  }
});

/**
 * Guards the registry itself: every `path: "..."` declared in the frontend's
 * route modules must be covered by an entry in e2e/routes.ts, so a new screen
 * cannot skip the responsive check.
 */
test("@responsive route registry covers every SPA route", () => {
  const files: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name === "routes.tsx") files.push(full);
    }
  };
  walk(path.join(FRONTEND_DIR, "src", "features"));
  walk(path.join(FRONTEND_DIR, "src", "portal"));
  expect(files.length).toBeGreaterThan(5);

  const registered = ROUTES.map((r) => r.path);
  const missing: string[] = [];
  for (const file of files) {
    const source = readFileSync(file, "utf8");
    for (const match of source.matchAll(/\bpath:\s*"([^"]+)"/g)) {
      const declared = match[1] ?? "";
      if (declared === "/") continue; // index routes are covered by their parent
      if (!registered.some((p) => p === declared || p.endsWith(declared))) {
        missing.push(`${path.relative(FRONTEND_DIR, file)}: ${declared}`);
      }
    }
  }
  expect(missing, "add these routes to e2e/routes.ts").toEqual([]);
});
