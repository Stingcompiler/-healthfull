/**
 * The marketing page at /login (ADR 0027): a sales showcase whose one action is the staff
 * sign-in at /sign-in. It is a deployment setting (MARKETING_SITE), off by default, so the rest of
 * the suite keeps the plain sign-in at /login. The backend's switch is proved by pytest
 * (apps/ops/tests/test_site.py) and, here, by reading the real endpoint; this spec turns the
 * page ON by answering GET /api/ops/site in the browser, then drives the real sign-in.
 *
 * Matrix: 3 viewports x 3 themes x 2 languages, no horizontal scroll, no console errors,
 * screenshots in artifacts/screens/marketing-*.png (light/ar, dark/en and warm/ar).
 */
import { expect, test, type Page } from "@playwright/test";

import { BASE_URL } from "../../env";
import { ADMIN_STATE, ANONYMOUS_STATE } from "../../fixtures/state";
import {
  expectNoHorizontalScroll,
  expectPrefsApplied,
  LANGS,
  loginForm,
  setPrefs,
  snap,
  submitLogin,
  THEMES,
  tr,
  trackConsoleErrors,
  type Lang,
} from "../../helpers";
import { E2E_PASSWORD, resolveUser } from "../../fixtures/users";

const VIEWPORTS = [
  { label: "phone", width: 375, height: 812 },
  { label: "tablet", width: 768, height: 1024 },
  { label: "desktop", width: 1280, height: 800 },
] as const;

const SCREENSHOT_COMBOS: ReadonlySet<string> = new Set([
  "light/ar",
  "dark/en",
  "warm/ar",
]);

/**
 * Turns the page on for this browser page only, the way a deployment with MARKETING_SITE=1
 * answers, for a center whose own website is off (it would win at `/`, ADR 0028 decision 4);
 * patient sign-in and booking stay on as the seed has them.
 */
async function marketingOn(
  page: Page,
  contact: { email?: string; whatsapp?: string } = {},
): Promise<void> {
  await page.route("**/api/ops/site", (route) =>
    route.fulfill({
      json: {
        marketing: true,
        contact_email: contact.email ?? null,
        contact_whatsapp: contact.whatsapp ?? null,
        center_site: false,
        online_booking: true,
        patient_tracking: true,
      },
    }),
  );
}

const copy = (lang: Lang, key: string) => tr(lang, `marketing:${key}`);

test.describe("@marketing page", () => {
  test.use({ storageState: ANONYMOUS_STATE });

  for (const viewport of VIEWPORTS) {
    test.describe(`${String(viewport.width)}x${String(viewport.height)}`, () => {
      test.use({
        viewport: { width: viewport.width, height: viewport.height },
      });

      for (const theme of THEMES) {
        for (const lang of LANGS) {
          test(`${theme} ${lang}`, async ({ page }) => {
            const logged = trackConsoleErrors(page, { allowAnonymousMe: true });
            await marketingOn(page);
            await setPrefs(page, { theme, lang });
            await page.goto("/login");
            await expect(page.getByRole("heading", { level: 1 })).toHaveText(
              copy(lang, "hero.title"),
            );
            await expectPrefsApplied(page, { theme, lang });
            await page.evaluate(() =>
              document.fonts.ready.then(() => undefined),
            );
            await expect(page).toHaveTitle(copy(lang, "meta.title"));
            await expectNoHorizontalScroll(page);

            // Every lazy screenshot in view of the full-page capture, so the picture is complete.
            if (SCREENSHOT_COMBOS.has(`${theme}/${lang}`)) {
              await page.evaluate(async () => {
                for (const img of Array.from(document.images))
                  img.loading = "eager";
                await Promise.all(
                  Array.from(document.images).map((img) =>
                    img.decode().catch(() => undefined),
                  ),
                );
              });
              await page.waitForLoadState("networkidle");
              await snap(page, "marketing");
            }
            await expectNoHorizontalScroll(page);
            expect(logged.errors(), "console errors / page errors").toEqual([]);
          });
        }
      }
    });
  }

  test("the call to action appears at least five times and every one leads to /sign-in", async ({
    page,
  }) => {
    await marketingOn(page);
    await setPrefs(page, { theme: "light", lang: "en" });
    await page.goto("/login");
    const ctas = page.getByTestId("mk-cta");
    await expect(ctas.first()).toBeVisible();
    expect(await ctas.count()).toBeGreaterThanOrEqual(5);
    for (const cta of await ctas.all()) {
      await expect(cta).toHaveAttribute("href", "/sign-in");
      await expect(cta).toHaveText(copy("en", "cta"));
    }
    // After each persuading section, in the order of the page.
    const places = await ctas.evaluateAll((all) =>
      all.map((el) => el.getAttribute("data-cta")),
    );
    expect(places).toEqual([
      "header",
      "hero",
      "cycle",
      "safety",
      "roles",
      "network",
      "final",
      "bar",
    ]);
  });

  test("the sign-in works from the call to action, keeps its form, and sign-out returns to /sign-in", async ({
    page,
  }) => {
    test.setTimeout(60_000);
    await marketingOn(page);
    await setPrefs(page, { theme: "light", lang: "en" });
    await page.goto("/login");
    await page.getByTestId("mk-cta").nth(1).click();
    await expect(page).toHaveURL(/\/sign-in$/);
    const form = loginForm(page);
    await expect(form.submit).toBeVisible();
    // The staff form keeps its accessible names (ADR 0027): the same ones /login has when off.
    await expect(
      page.getByRole("form", { name: tr("en", "auth:login.title") }),
    ).toBeVisible();
    await expect(
      page.getByLabel(new RegExp(tr("en", "auth:login.username"))),
    ).toBeVisible();
    await submitLogin(page, resolveUser("admin").username, E2E_PASSWORD);
    await expect(page.getByTestId("user-menu")).toBeVisible();
    await page.getByTestId("user-menu").click();
    await page.getByTestId("logout").click();
    await expect(page).toHaveURL(/\/sign-in(\?|$)/);
    await expect(form.submit).toBeVisible();
  });

  test("a signed-out visit to a staff screen is sent to /sign-in with the way back", async ({
    page,
  }) => {
    await marketingOn(page);
    await page.goto("/patients");
    await expect(page).toHaveURL(/\/sign-in\?redirect=%2Fpatients/);
    await expect(loginForm(page).submit).toBeVisible();
  });

  test("the phone bar is fixed to the bottom and never covers the last line", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await marketingOn(page);
    await setPrefs(page, { theme: "light", lang: "ar" });
    await page.goto("/login");
    const bar = page.getByTestId("mk-bottom-bar");
    await expect(bar).toBeVisible();
    await page.evaluate(() =>
      window.scrollTo(0, document.documentElement.scrollHeight),
    );
    const footer = page.locator("footer");
    await expect(footer).toBeInViewport();
    const boxes = await page.evaluate(() => {
      const f = document.querySelector("footer")?.getBoundingClientRect();
      const b = document
        .querySelector('[data-testid="mk-bottom-bar"]')
        ?.getBoundingClientRect();
      return { footerBottom: f?.bottom ?? 0, barTop: b?.top ?? 0 };
    });
    expect(boxes.footerBottom).toBeLessThanOrEqual(boxes.barTop + 1);
    // From tablet up the bar is gone and the sticky header carries the button.
    await page.setViewportSize({ width: 1280, height: 800 });
    await expect(bar).toBeHidden();
    await expect(page.locator('[data-cta="header"]')).toBeVisible();
  });

  test("the header stays on screen while scrolling", async ({ page }) => {
    await marketingOn(page);
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/login");
    await page.evaluate(() => window.scrollTo(0, 2500));
    await expect(page.locator('[data-cta="header"]')).toBeInViewport();
  });

  test("the FAQ opens and closes from the keyboard", async ({ page }) => {
    await marketingOn(page);
    await setPrefs(page, { theme: "light", lang: "en" });
    await page.goto("/login");
    const first = page.locator(".mk-faq summary").first();
    await first.scrollIntoViewIfNeeded();
    await first.focus();
    const answer = page.getByText(copy("en", "faq.a1"));
    await expect(answer).toBeHidden();
    await page.keyboard.press("Enter");
    await expect(answer).toBeVisible();
    await page.keyboard.press("Space");
    await expect(answer).toBeHidden();
    const count = await page.locator(".mk-faq details").count();
    expect(count).toBeGreaterThanOrEqual(4);
    expect(count).toBeLessThanOrEqual(8);
  });

  test("language and theme switches work on the page", async ({ page }) => {
    await marketingOn(page);
    await setPrefs(page, { theme: "light", lang: "ar" });
    await page.goto("/login");
    await page.getByRole("button", { name: /English/ }).click();
    await expectPrefsApplied(page, { theme: "light", lang: "en" });
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      copy("en", "hero.title"),
    );
    await page.getByRole("button", { name: tr("en", "theme.change") }).click();
    await page
      .getByRole("menuitemradio", { name: tr("en", "theme.dark") })
      .click();
    await expectPrefsApplied(page, { theme: "dark", lang: "en" });
  });

  test("contact shows only what the deployment configures, and never an account or a password", async ({
    page,
  }) => {
    await marketingOn(page);
    await setPrefs(page, { theme: "light", lang: "en" });
    await page.goto("/login");
    await expect(
      page.locator('a[href^="mailto:"], a[href^="https://wa.me/"]'),
    ).toHaveCount(0);
    await expect(page.getByText(copy("en", "final.demo"))).toBeVisible();
    await page.unroute("**/api/ops/site");
    await marketingOn(page, {
      email: "sales@example.org",
      whatsapp: "249912345678",
    });
    await page.reload();
    await expect(
      page.locator('a[href="mailto:sales@example.org"]'),
    ).toBeVisible();
    await expect(
      page.locator('a[href="https://wa.me/249912345678"]'),
    ).toBeVisible();
    const text = (await page.locator("body").innerText()).toLowerCase();
    expect(text).not.toContain(E2E_PASSWORD.toLowerCase());
    expect(text).not.toContain("password");
    await expect(page.locator("input")).toHaveCount(0);
  });

  test("first load: no outside request, only the hero picture is fetched, and it is under 250 KB", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    const origin = new URL(BASE_URL).origin;
    const outside: string[] = [];
    const pictures: { url: string; bytes: number }[] = [];
    page.on("response", (response) => {
      const url = response.url();
      if (
        !url.startsWith(origin) &&
        !url.startsWith("data:") &&
        !url.startsWith("blob:")
      )
        outside.push(url);
      // Vite's dev server also answers a JavaScript module per picture (`?import`); only real images count.
      if (
        /\.webp(\?|$)/.test(url) &&
        (response.headers()["content-type"] ?? "").startsWith("image/")
      ) {
        void response
          .body()
          .then((body) => pictures.push({ url, bytes: body.length }))
          .catch(() => undefined);
      }
    });
    await marketingOn(page);
    await setPrefs(page, { theme: "light", lang: "ar" });
    await page.goto("/login");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.waitForLoadState("networkidle");
    expect(outside, "requests to another origin").toEqual([]);
    const hero = pictures.find((p) => p.url.includes("/hero-"));
    expect(hero, "the hero picture is fetched").toBeDefined();
    expect(hero?.bytes ?? Infinity).toBeLessThan(250 * 1024);
    // The browser prefetches lazy pictures a screen or two ahead; the far ones wait for the scroll.
    expect(
      pictures.some((p) => p.url.includes("portal-results")),
      `fetched before scrolling: ${pictures.map((p) => p.url).join(", ")}`,
    ).toBe(false);
    const before = pictures.reduce((sum, p) => sum + p.bytes, 0);
    expect(before, "picture bytes before scrolling").toBeLessThan(400 * 1024);
    // Below-the-fold pictures arrive when scrolled to.
    await page
      .getByRole("img", { name: tr("ar", "marketing:portal.resultsAlt") })
      .scrollIntoViewIfNeeded();
    await expect
      .poll(() => pictures.some((p) => p.url.includes("portal-results")))
      .toBe(true);
  });

  test("reduced motion: the FAQ chevron does not animate", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await marketingOn(page);
    await page.goto("/login");
    const duration = await page
      .locator(".mk-faq-chevron")
      .first()
      .evaluate((el) => getComputedStyle(el).transitionDuration);
    expect(parseFloat(duration)).toBeLessThan(0.05);
  });
});

test.describe("@marketing site root", () => {
  test.describe("signed out", () => {
    test.use({ storageState: ANONYMOUS_STATE });

    test("/ shows the page with the eight calls to action, all to /sign-in", async ({
      page,
    }) => {
      await marketingOn(page);
      await setPrefs(page, { theme: "light", lang: "en" });
      await page.goto("/");
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(
        copy("en", "hero.title"),
      );
      expect(new URL(page.url()).pathname).toBe("/");
      const ctas = page.getByTestId("mk-cta");
      expect(await ctas.count()).toBe(8);
      for (const cta of await ctas.all())
        await expect(cta).toHaveAttribute("href", "/sign-in");
      await page.locator('[data-cta="hero"]').click();
      await expect(page).toHaveURL(/\/sign-in$/);
      await expect(loginForm(page).submit).toBeVisible();
    });

    test("a protected route still goes to /sign-in", async ({ page }) => {
      await marketingOn(page);
      await page.goto("/queue");
      await expect(page).toHaveURL(/\/sign-in\?redirect=%2Fqueue/);
    });

    test("/portal stays the portal (its sign-in while the center website is off)", async ({ page }) => {
      await marketingOn(page);
      await page.goto("/portal");
      await expect(page.getByTestId("marketing-page")).toHaveCount(0);
      await expect(page).toHaveURL(/\/portal\/sign-in$/);
      await expect(page.locator("#main h1").first()).toBeVisible();
    });
  });

  test.describe("signed in", () => {
    test.use({ storageState: ADMIN_STATE });

    test("/ is the dashboard, and the page never appears", async ({ page }) => {
      await marketingOn(page);
      await page.goto("/");
      await expect(page.getByTestId("user-menu")).toBeVisible();
      await expect(page.getByTestId("marketing-page")).toHaveCount(0);
    });
  });
});

test.describe("@marketing off by default", () => {
  test.use({ storageState: ANONYMOUS_STATE });

  test("the server says off, /login is the sign-in form and /sign-in is its alias", async ({
    page,
  }) => {
    await setPrefs(page, { theme: "light", lang: "en" });
    const site = (await (
      await page.context().request.get("/api/ops/site")
    ).json()) as { marketing: boolean };
    expect(site.marketing).toBe(false);
    for (const path of ["/login", "/sign-in"]) {
      await page.goto(path);
      await expect(
        page.getByRole("form", { name: tr("en", "auth:login.title") }),
      ).toBeVisible();
      await expect(page.getByTestId("marketing-page")).toHaveCount(0);
    }
    // Off, a signed-out staff screen still goes to /login.
    await page.goto("/patients");
    await expect(page).toHaveURL(/\/login\?redirect=%2Fpatients/);
  });
});
