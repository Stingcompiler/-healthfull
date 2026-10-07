/**
 * No runtime internet dependency (CLAUDE.md, ARCHITECTURE 8): the center runs
 * on an isolated LAN. While signing in, using the dashboard and walking the
 * whole style guide (every shared component, both font families, both
 * languages), the browser must not contact any host but this machine.
 *
 * Non-local requests are recorded AND aborted, so a CDN fallback cannot hide
 * behind a successful load.
 */
import { expect, test } from "@playwright/test";

import { LOCAL_HOSTNAMES } from "../env";
import { ANONYMOUS_STATE } from "../fixtures/state";
import { login, logout, setPrefs, trackConsoleErrors, type Lang } from "../helpers";

test.use({ storageState: ANONYMOUS_STATE });

function isExternal(raw: string): boolean {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return false;
  }
  if (!["http:", "https:", "ws:", "wss:"].includes(url.protocol)) return false; // data:, blob:, about:
  return !LOCAL_HOSTNAMES.has(url.hostname);
}

interface FontReport {
  failed: string[];
  loadedFamilies: string[];
}

for (const lang of ["ar", "en"] as const satisfies readonly Lang[]) {
  test(`@offline login, dashboard and design make no request outside localhost (${lang})`, async ({
    page,
    context,
  }) => {
    const external: string[] = [];
    context.on("request", (request) => {
      if (isExternal(request.url())) external.push(`${request.method()} ${request.url()}`);
    });
    page.on("websocket", (socket) => {
      if (isExternal(socket.url())) external.push(`WS ${socket.url()}`);
    });
    await context.route(
      (url) => isExternal(url.href),
      (route) => route.abort("internetdisconnected"),
    );
    const logged = trackConsoleErrors(page, { allowAnonymousMe: true });

    // The login screen in the wanted language (local cache), then the same for the profile.
    await setPrefs(page, { theme: "light", lang });
    await login(page, "manager");
    await setPrefs(page, { theme: "light", lang });
    await expect(page.locator("html")).toHaveAttribute("lang", lang);
    await expect(page.locator("#main h1")).toBeVisible();
    await page.waitForLoadState("networkidle");

    await page.goto("/design");
    await expect(page.locator("#main h1")).toBeVisible();
    // Walk to the bottom so every section (and anything lazy) renders.
    await page.evaluate(async () => {
      for (let y = 0; y < document.documentElement.scrollHeight; y += window.innerHeight) {
        window.scrollTo(0, y);
        await new Promise((resolve) => setTimeout(resolve, 50));
      }
    });
    await page.waitForLoadState("networkidle");

    // Fonts are bundled: every face the page asked for loaded from this origin.
    const fonts = await page.evaluate(async (): Promise<FontReport> => {
      await document.fonts.ready;
      const faces = Array.from(document.fonts);
      return {
        failed: faces.filter((f) => f.status === "error").map((f) => `${f.family} ${f.weight}`),
        loadedFamilies: [...new Set(faces.filter((f) => f.status === "loaded").map((f) => f.family))],
      };
    });
    expect(fonts.failed, "font faces that failed to load").toEqual([]);
    const expectedFamily = lang === "ar" ? "IBM Plex Sans Arabic" : "Inter Variable";
    expect(fonts.loadedFamilies.map((f) => f.replace(/["']/g, ""))).toContain(expectedFamily);

    await logout(page);

    expect(external, "requests to non-local origins").toEqual([]);
    expect(logged.errors(), "console errors / page errors").toEqual([]);
  });
}
