import { expect, type Page } from "@playwright/test";

interface Overflow {
  scrollWidth: number;
  innerWidth: number;
  offenders: string[];
}

/**
 * ARCHITECTURE 5.3: no horizontal page scroll at any breakpoint, asserted as
 * `document.documentElement.scrollWidth <= innerWidth`. On failure the message
 * lists the elements that stick out (either side: RTL overflows to the left).
 */
export async function expectNoHorizontalScroll(page: Page): Promise<void> {
  const result = await page.evaluate((): Overflow => {
    const root = document.documentElement;
    const innerWidth = window.innerWidth;
    const offenders: string[] = [];
    if (root.scrollWidth > innerWidth) {
      for (const el of Array.from(document.body.querySelectorAll<HTMLElement>("*"))) {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) continue;
        if (rect.right > innerWidth + 1 || rect.left < -1) {
          if (offenders.length >= 8) break; // enough to locate the culprit
          const id = el.id ? `#${el.id}` : "";
          const testId = el.dataset.testid ? `[data-testid=${el.dataset.testid}]` : "";
          const cls = typeof el.className === "string" ? `.${el.className.trim().split(/\s+/).slice(0, 4).join(".")}` : "";
          offenders.push(
            `${el.tagName.toLowerCase()}${id}${testId}${cls} left=${String(Math.round(rect.left))} right=${String(Math.round(rect.right))}`,
          );
        }
      }
    }
    return { scrollWidth: root.scrollWidth, innerWidth, offenders };
  });
  expect(
    result.scrollWidth,
    `horizontal scroll: scrollWidth ${String(result.scrollWidth)} > innerWidth ${String(result.innerWidth)}\n` +
      result.offenders.join("\n"),
  ).toBeLessThanOrEqual(result.innerWidth);
}
