import { expect, type Page } from "@playwright/test";

import { BASE_URL } from "../env";
import { csrfHeaders, isLoggedIn } from "./auth";
import type { Lang } from "./i18n";

export const THEMES = ["light", "dark", "warm"] as const;
export type Theme = (typeof THEMES)[number];

export interface Prefs {
  theme: Theme;
  lang: Lang;
}

/** localStorage keys of the first-paint cache (frontend/src/lib/preferences.ts, public/boot.js). */
const THEME_KEY = "hs.theme";
const LANG_KEY = "hs.lang";

function writeCache({ theme, lang, themeKey, langKey }: Prefs & { themeKey: string; langKey: string }): void {
  try {
    window.localStorage.setItem(themeKey, theme);
    window.localStorage.setItem(langKey, lang);
  } catch {
    // about:blank and opaque origins have no storage; the next app page gets it.
  }
}

/**
 * Applies theme and language the way a user's choice persists:
 *
 * - always: the browser cache (localStorage) that boot.js reads before first
 *   paint, for every later navigation of this page (an init script), so
 *   logged-out screens (login, portal, 404) open in the wanted look;
 * - when the context is logged in: the server profile through
 *   PATCH /api/auth/me/preferences, which wins over the cache once /me loads.
 *
 * If the page is already showing the app it is reloaded so the change applies.
 */
export async function setPrefs(page: Page, prefs: Prefs): Promise<void> {
  const args = { ...prefs, themeKey: THEME_KEY, langKey: LANG_KEY };
  await page.addInitScript(writeCache, args);

  if (await isLoggedIn(page)) {
    const response = await page.context().request.patch("/api/auth/me/preferences", {
      headers: await csrfHeaders(page.context()),
      data: { theme: prefs.theme, language: prefs.lang },
    });
    expect(response.status(), `PATCH /api/auth/me/preferences: ${await response.text()}`).toBe(200);
  }

  if (page.url().startsWith(BASE_URL)) {
    await page.evaluate(writeCache, args);
    await page.reload();
  }
}

/** The document reflects the preferences: data-theme, lang and dir on <html>. */
export async function expectPrefsApplied(page: Page, { theme, lang }: Prefs): Promise<void> {
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-theme", theme);
  await expect(html).toHaveAttribute("lang", lang);
  await expect(html).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
}
