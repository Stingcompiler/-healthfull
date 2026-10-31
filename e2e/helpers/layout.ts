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

/**
 * A stepper's visible pieces never collide (D-0024): the painted text of every visible
 * `[data-step-label]` and every `[data-step-mark]` under `root` is measured (text ranges, so
 * text that spills out of a squeezed box counts where it is drawn), and no two of them may
 * intersect; each must also stay inside the viewport and inside its own element (no clipping).
 * Visually hidden labels (sr-only, 1px boxes) are skipped.
 */
export async function expectStepLabelsApart(page: Page, rootSelector: string): Promise<void> {
  const problems = await page.evaluate((selector): string[] => {
    const root = document.querySelector(selector);
    if (!root) return [`no stepper ${selector}`];
    interface Box {
      name: string;
      l: number;
      r: number;
      t: number;
      b: number;
    }
    const boxes: Box[] = [];
    const out: string[] = [];
    const big = (r: DOMRect) => r.width > 1.5 && r.height > 1.5;
    for (const el of Array.from(root.querySelectorAll<HTMLElement>("[data-step-label], [data-step-mark]"))) {
      const own = el.getBoundingClientRect();
      if (!big(own) || !el.checkVisibility()) continue;
      const name = `${el.hasAttribute("data-step-mark") ? "mark" : "label"} "${(el.textContent ?? "").trim()}"`;
      let rects: DOMRect[] = [own];
      if (el.hasAttribute("data-step-label")) {
        // The painted text only: text inside a visually hidden child (sr-only "done") is skipped.
        rects = [];
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        for (let node = walker.nextNode(); node; node = walker.nextNode()) {
          let hidden = false;
          for (let up = node.parentElement; up && up !== el; up = up.parentElement) {
            if (!big(up.getBoundingClientRect())) hidden = true;
          }
          if (hidden) continue;
          const range = document.createRange();
          range.selectNodeContents(node);
          rects.push(...Array.from(range.getClientRects()).filter(big));
        }
        if (rects.length === 0) continue;
      }
      const l = Math.min(...rects.map((r) => r.left));
      const r = Math.max(...rects.map((x) => x.right));
      const t = Math.min(...rects.map((x) => x.top));
      const b = Math.max(...rects.map((x) => x.bottom));
      if (l < -0.5 || r > window.innerWidth + 0.5) out.push(`${name} leaves the viewport (${String(l)}..${String(r)})`);
      if (l < own.left - 1 || r > own.right + 1 || el.scrollWidth > el.clientWidth + 1) {
        out.push(`${name} spills out of its box`);
      }
      boxes.push({ name, l, r, t, b });
    }
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i];
        const c = boxes[j];
        if (!a || !c) continue;
        const x = Math.min(a.r, c.r) - Math.max(a.l, c.l);
        const y = Math.min(a.b, c.b) - Math.max(a.t, c.t);
        if (x > 0.5 && y > 0.5) out.push(`${a.name} overlaps ${c.name}`);
      }
    }
    return out;
  }, rootSelector);
  expect(problems, `stepper ${rootSelector}`).toEqual([]);
}
