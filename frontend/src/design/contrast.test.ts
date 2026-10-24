import { describe, expect, it } from "vitest";

import { AA_NON_TEXT, blend, contrastRatio, parseThemes, type ThemeName } from "./contrast";
import tokensCss from "./tokens.css?raw";
import contrast from "./tokens/contrast.json";
import darkTokens from "./tokens/dark.tokens.json";
import lightTokens from "./tokens/light.tokens.json";
import warmTokens from "./tokens/warm.tokens.json";

/** Every component source, to check the classes actually used (not just the tokens). */
const SOURCES = import.meta.glob<string>(["../**/*.tsx", "!../**/*.test.tsx"], {
  query: "?raw",
  import: "default",
  eager: true,
});

const themes = parseThemes(tokensCss);
const THEMES: ThemeName[] = ["light", "dark", "warm"];

/**
 * [foreground, background, minimum ratio]. The pairs live in tokens/contrast.json so that
 * scripts/check_contrast.py (make tokens, make tokens-check, CI) checks exactly the same list.
 */
type Pair = readonly [string, string, number];

const PAIRS = contrast.pairs as unknown as Pair[];

describe("design tokens", () => {
  it.each(THEMES)("%s theme defines the brand values from ARCHITECTURE 5.1", (theme) => {
    const expected = {
      light: { primary: "#0d9488", bg: "#f8fafc", surface: "#ffffff", fg: "#0f172a" },
      dark: { primary: "#2dd4bf", bg: "#0b1220", surface: "#111a2e", fg: "#e2e8f0" },
      warm: { primary: "#4f46e5", bg: "#faf8f5", surface: "#ffffff", fg: "#1c1917" },
    }[theme];
    for (const [token, value] of Object.entries(expected)) {
      expect(themes[theme][token]?.toLowerCase(), `${theme} --${token}`).toBe(value);
    }
  });

  it("every theme defines the same token names", () => {
    const names = (t: ThemeName) => Object.keys(themes[t]).sort();
    expect(names("dark")).toEqual(names("light"));
    expect(names("warm")).toEqual(names("light"));
  });

  it.each(THEMES)("%s: tokens.css carries exactly the values in the DTCG source", (theme) => {
    // tokens.css is generated; this fails if it was edited by hand or not regenerated.
    const source = { light: lightTokens, dark: darkTokens, warm: warmTokens }[theme] as Record<string, unknown>;
    const fromJson: Record<string, string> = {};
    for (const group of Object.values(source)) {
      if (typeof group !== "object" || group === null) continue;
      for (const [name, token] of Object.entries(
        group as Record<string, { $type?: string; $value?: { hex?: string } }>,
      )) {
        if (token.$type === "color" && token.$value?.hex && !("alpha" in token.$value))
          fromJson[name] = token.$value.hex;
      }
    }
    expect(Object.keys(fromJson).length).toBeGreaterThan(40);
    for (const [name, hex] of Object.entries(fromJson)) {
      expect(themes[theme][name]?.toLowerCase(), `${theme} --${name}`).toBe(hex.toLowerCase());
    }
  });

  describe.each(THEMES)("%s theme meets WCAG AA", (theme) => {
    const tokens = themes[theme];
    it.each(PAIRS)("--%s on --%s >= %s:1", (fg, bg, min) => {
      const fgValue = tokens[fg];
      const bgValue = tokens[bg];
      expect(fgValue, `--${fg} missing`).toBeDefined();
      expect(bgValue, `--${bg} missing`).toBeDefined();
      const ratio = contrastRatio(fgValue ?? "", bgValue ?? "");
      expect(ratio, `${theme}: --${fg} ${String(fgValue)} on --${bg} ${String(bgValue)}`).toBeGreaterThanOrEqual(min);
    });
  });
});

describe("indicators as components actually draw them", () => {
  // A token can pass at full strength while the rendered control fails because a component
  // thins it with an alpha (ring-ring/35, border-border-strong/70): those ratios were 1.5-2.6:1.
  // Non-text indicators therefore must use these tokens at full strength.
  const INDICATOR_TOKENS = ["ring", "border-strong"] as const;
  const THINNED = new RegExp(
    String.raw`\b(?:[\w-]+:)*(?:ring|outline|border|bg|before:bg|after:bg)-(${INDICATOR_TOKENS.join("|")})\/(\d{1,3})\b`,
    "g",
  );

  it("no component draws --ring or --border-strong with an alpha", () => {
    const offenders: string[] = [];
    for (const [file, source] of Object.entries(SOURCES)) {
      for (const match of source.matchAll(THINNED)) offenders.push(`${file}: ${match[0]}`);
    }
    expect(offenders).toEqual([]);
  });

  it("no component turns the focus outline off without drawing a solid one", () => {
    const offenders = Object.entries(SOURCES)
      .filter(([, source]) => /focus-visible:outline-none|focus-visible:ring-\[?\d/.test(source))
      .map(([file]) => file);
    expect(offenders).toEqual([]);
  });

  it("the old translucent styles really were below 3:1 (guards the blend math)", () => {
    const light = themes.light;
    const ring35 = blend(light.ring ?? "", light.surface ?? "", 0.35);
    expect(contrastRatio(ring35, light.surface ?? "")).toBeLessThan(AA_NON_TEXT);
    const border70 = blend(light["border-strong"] ?? "", light.surface ?? "", 0.7);
    expect(contrastRatio(border70, light.surface ?? "")).toBeLessThan(AA_NON_TEXT);
    expect(contrastRatio(light.accent ?? "", light["surface-raised"] ?? "")).toBeLessThan(AA_NON_TEXT);
  });
});

describe("contrastRatio", () => {
  it("matches known reference values", () => {
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(contrastRatio("#ffffff", "#ffffff")).toBeCloseTo(1, 5);
    expect(contrastRatio("#777777", "#ffffff")).toBeCloseTo(4.48, 2);
    expect(contrastRatio("#fff", "#000")).toBeCloseTo(21, 5);
  });

  it("blends like the browser", () => {
    expect(blend("#000000", "#ffffff", 0.5)).toBe("#808080");
    expect(blend("#0d9488", "#ffffff", 1)).toBe("#0d9488");
    expect(blend("#0d9488", "#ffffff", 0)).toBe("#ffffff");
  });
});
