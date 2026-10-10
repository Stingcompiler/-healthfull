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

import { BASE_URL, FRONTEND_DIR } from "../env";
import { ADMIN_STATE, ANONYMOUS_STATE, PHARMACIST_STATE } from "../fixtures/state";
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
import { routeByName, ROUTES, visitPath } from "../routes";

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

              const target = await visitPath(route);
              if (route.prepare) await route.prepare(page);
              await page.goto(target);
              await expect(route.ready(page)).toBeVisible();
              // Still on the route: no bounce to /login, no redirect elsewhere.
              expect(new URL(page.url()).pathname).toBe(new URL(target, BASE_URL).pathname);
              await expectPrefsApplied(page, { theme, lang });
              await page.evaluate(() => document.fonts.ready.then(() => undefined));

              // Data requests settle before measuring and capturing: no skeletons in the pictures.
              await page.waitForLoadState("networkidle");
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
        // The active (bold, widest) tab's label: the first cell is the dashboard.
        const span = nav.querySelector<HTMLElement>('li a [data-slot="nav-label"]');
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
 * A role with few modules: the shell must not leave empty tab-bar cells or a pointless
 * "More" (the matrix above only uses the admin, who sees every module).
 */
test.describe("@responsive sparse role (pharmacist)", () => {
  test.use({ storageState: PHARMACIST_STATE });

  for (const viewport of VIEWPORTS) {
    for (const [theme, lang] of [
      ["light", "ar"],
      ["dark", "en"],
    ] as const) {
      test(`dashboard ${String(viewport.width)}x${String(viewport.height)} ${theme} ${lang}`, async ({ page }) => {
        await page.setViewportSize({ width: viewport.width, height: viewport.height });
        const logged = trackConsoleErrors(page);
        await setPrefs(page, { theme, lang });
        await page.goto("/");
        await expect(routeByName("dashboard").ready(page)).toBeVisible();
        await expectPrefsApplied(page, { theme, lang });
        await expectNoHorizontalScroll(page);

        if (viewport.width < 768) {
          const bar = page.locator('[data-slot="app-bottom-nav"]');
          await expect(bar).toBeVisible();
          await expect(bar.getByTestId("nav-more")).toHaveCount(0);
          // The cells share the full bar: no empty grid tracks.
          const fill = await bar.locator("ul").evaluate((list) => {
            const cells = Array.from(list.children).map((li) => li.getBoundingClientRect().width);
            return { cells, used: cells.reduce((a, b) => a + b, 0), width: list.getBoundingClientRect().width };
          });
          expect(fill.cells.length).toBeGreaterThan(0);
          expect(fill.used).toBeGreaterThanOrEqual(fill.width - 2);
        }
        await snap(page, "dashboard-pharmacist");
        expect(logged.errors(), "console errors / page errors").toEqual([]);
      });
    }
  }
});

/**
 * Touch targets on phones (375px): every interactive control is at least 44x44 CSS px.
 * Inline links inside running text are exempt (WCAG 2.5.8), so only non-inline boxes count.
 */
test.describe("@responsive touch targets at 375px", () => {
  test.use({ viewport: { width: 375, height: 812 } });

  for (const name of ["login", "portal", "dashboard", "change-password"]) {
    const route = routeByName(name);
    test(`${name}: controls are at least 44x44`, async ({ browser }) => {
      const context = await browser.newContext({
        storageState: route.auth ? ADMIN_STATE : ANONYMOUS_STATE,
        viewport: { width: 375, height: 812 },
      });
      const page = await context.newPage();
      try {
        await setPrefs(page, { theme: "light", lang: "ar" });
        await page.goto(await visitPath(route));
        await expect(route.ready(page)).toBeVisible();
        await page.evaluate(() => document.fonts.ready.then(() => undefined));
        const small = await page.evaluate(() => {
          const selector = [
            "a[href]",
            "button",
            "input:not([type=hidden]):not([type=checkbox]):not([type=radio])",
            "select",
            "textarea",
            "[role=button]",
            "[role=tab]",
            "[role=radio]",
            "[role=switch]",
          ].join(",");
          const out: string[] = [];
          for (const el of Array.from(document.querySelectorAll<HTMLElement>(selector))) {
            const style = getComputedStyle(el);
            if (style.display === "inline" || style.visibility === "hidden") continue;
            if (el.closest("[aria-hidden=true], [inert]")) continue;
            const rect = el.getBoundingClientRect();
            if (rect.width <= 1 || rect.height <= 1) continue; // visually hidden (sr-only, skip link)
            if (rect.width < 43.5 || rect.height < 43.5) {
              const label = (el.getAttribute("aria-label") ?? el.textContent ?? "").trim().slice(0, 40);
              out.push(`${el.tagName.toLowerCase()} "${label}" ${String(Math.round(rect.width))}x${String(Math.round(rect.height))}`);
            }
          }
          return out;
        });
        expect(small, "controls smaller than 44x44 at 375px").toEqual([]);
      } finally {
        await context.close();
      }
    });
  }
});

/** Sudanese names have four parts; the identity card must show every one at phone width. */
test.describe("@responsive four-part patient names at 375px", () => {
  test.use({ viewport: { width: 375, height: 812 }, storageState: ADMIN_STATE });

  for (const lang of LANGS) {
    test(`patient card shows the whole name (${lang})`, async ({ page }) => {
      await setPrefs(page, { theme: "light", lang });
      await page.goto("/design#cards");
      const card = page.locator('[data-slot="patient-card"]').first();
      await expect(card).toBeVisible();
      for (const text of ["فاطمة عثمان محمد الحسن", "Fatima Osman Mohamed Alhassan"]) {
        const line = card.getByText(text, { exact: true });
        await expect(line).toBeVisible();
        const clipped = await line.evaluate((el) => {
          const style = getComputedStyle(el);
          return el.scrollWidth > el.clientWidth + 1 || style.textOverflow === "ellipsis";
        });
        expect(clipped, `"${text}" is cut off`).toBe(false);
      }
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
