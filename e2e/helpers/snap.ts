import { mkdirSync } from "node:fs";
import path from "node:path";

import type { Page } from "@playwright/test";

import { SCREENS_DIR } from "../env";

/**
 * Saves a full-page screenshot for visual review (ARCHITECTURE 6):
 * artifacts/screens/<name>-<viewport>-<theme>-<lang>.png, e.g.
 * `login-375x812-light-ar.png`. Viewport, theme and language are read from the
 * page itself, so the file name always matches what was rendered.
 */
export async function snap(page: Page, name: string): Promise<string> {
  const size = page.viewportSize();
  const viewport = size ? `${String(size.width)}x${String(size.height)}` : "auto";
  const { theme, lang } = await page.evaluate(() => ({
    theme: document.documentElement.dataset.theme ?? "none",
    lang: document.documentElement.lang || "none",
  }));
  const safeName = name.replace(/[^a-z0-9-]+/gi, "-");
  const file = path.join(SCREENS_DIR, `${safeName}-${viewport}-${theme}-${lang}.png`);
  mkdirSync(SCREENS_DIR, { recursive: true });
  // Web fonts must be in before the pixels are taken.
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  await page.screenshot({ path: file, fullPage: true, animations: "disabled", caret: "hide", scale: "css" });
  return file;
}
