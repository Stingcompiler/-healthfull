// TEMPORARY debugging spec (integrator); deleted before the final run.
import { test } from "@playwright/test";

import { ANONYMOUS_STATE } from "../fixtures/state";
import { login, trackConsoleErrors } from "../helpers";

test.use({ storageState: ANONYMOUS_STATE });

for (const start of ["/", "/design", "/reports"]) {
  test(`@debug logout from ${start}`, async ({ page }) => {
    const logged = trackConsoleErrors(page, { allowAnonymousMe: true });
    const urls: string[] = [];
    page.on("framenavigated", (f) => {
      if (f === page.mainFrame()) urls.push(f.url());
    });
    await login(page, "manager");
    await page.goto(start);
    await page.locator("#main h1").waitFor();
    urls.length = 0;
    await page.getByTestId("user-menu").click();
    await page.getByTestId("logout").click();
    await page.waitForTimeout(1500);
    console.log(`START ${start}\nFINAL ${page.url()}\nNAVS ${String(urls.length)}: ${urls.slice(0, 6).join("\n  ")}`);
    console.log(`ERRORS ${JSON.stringify(logged.errors().map((e) => e.slice(0, 120)))}`);
  });
}
