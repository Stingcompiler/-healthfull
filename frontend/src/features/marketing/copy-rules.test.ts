/**
 * LANDING section 2 and 6, as tests over the copy itself: headline and subhead limits, short
 * sentences, short words, no invented evidence. The page may not grow a claim the repository
 * cannot prove without one of these failing.
 */
import { describe, expect, it } from "vitest";

import { ar, en } from "@/i18n/resources";

interface Tree {
  readonly [key: string]: string | Tree;
}

function leaves(tree: Tree, prefix = ""): [string, string][] {
  return Object.entries(tree).flatMap(([key, value]) =>
    typeof value === "string" ? [[`${prefix}${key}`, value] as [string, string]] : leaves(value, `${prefix}${key}.`),
  );
}

const words = (text: string) => text.split(/\s+/).filter(Boolean);
const sentences = (text: string) =>
  text
    .split(/[.!?؟]+\s+|[.!?؟]+$/)
    .map((s) => s.trim())
    .filter(Boolean);

const PAGES = { ar: ar.marketing, en: en.marketing } as const;

describe.each(Object.entries(PAGES))("marketing copy (%s)", (lang, tree) => {
  const all = leaves(tree);
  // The page text a visitor reads: not the SEO description, alt texts, or the brand name.
  const prose = all.filter(([key]) => !/^(meta\.|skip|preferences|brand)/.test(key) && !key.endsWith(".alt"));

  it("has a hero headline of at most 10 words", () => {
    expect(words(tree.hero.title).length).toBeLessThanOrEqual(10);
  });

  it("has a subhead of at most 20 words", () => {
    expect(words(tree.hero.lead).length).toBeLessThanOrEqual(20);
  });

  it("stays within the 745-word ceiling of LANDING section 2, repeated calls to action included", () => {
    const total = prose.reduce((sum, [, text]) => sum + words(text).length, 0) + 7 * words(tree.cta).length; // 8 buttons, one counted
    expect(total, `${lang}: ${String(total)} words`).toBeLessThanOrEqual(745);
  });

  it("keeps the average sentence at 14 words or fewer", () => {
    const all = prose.flatMap(([, text]) => sentences(text));
    const average = all.reduce((sum, s) => sum + words(s).length, 0) / all.length;
    expect(average, `${lang}: ${average.toFixed(1)} words per sentence`).toBeLessThanOrEqual(14);
  });

  it("keeps long words rare (15% or fewer)", () => {
    const limit = lang === "ar" ? 9 : 10; // letters; the Arabic count includes prefixes and suffixes
    const all = prose.flatMap(([, text]) => words(text)).map((w) => w.replace(/[^\p{L}]/gu, ""));
    const long = all.filter((w) => w.length > limit).length;
    expect(long / all.length, `${lang}: ${((long / all.length) * 100).toFixed(1)}% long words`).toBeLessThanOrEqual(
      0.15,
    );
  });

  it("claims no customers, numbers, ratings, prices or urgency", () => {
    const text = prose.map(([, t]) => t).join(" ");
    expect(text).not.toMatch(/\d/); // no counts, years, percentages or prices
    const banned =
      lang === "ar"
        ? /عميل|عملاء|شهادة|تقييم|نجوم|مرخّص|مرخص|معتمد من|محدود|ينتهي|خصم خاص|الأكثر|مجان|\$|دولار|جنيه/
        : /\b(customers?|clients?|testimonials?|ratings?|stars|certified|licensed|limited|offer ends|free|best|most popular)\b|#1|\$|USD|SDG/i;
    expect(text).not.toMatch(banned);
  });

  it("keeps the 4 to 8 FAQ questions real: each has an answer", () => {
    const questions = all.filter(([key]) => /^faq\.q\d+$/.test(key));
    expect(questions.length).toBeGreaterThanOrEqual(4);
    expect(questions.length).toBeLessThanOrEqual(8);
    for (const [key] of questions) expect(all.some(([k]) => k === key.replace(".q", ".a"))).toBe(true);
  });

  it("uses one wording for the call to action", () => {
    expect(tree.cta).toBe(lang === "ar" ? "الدخول إلى النظام" : "Sign in to the system");
  });
});
