import { describe, expect, it } from "vitest";

import { AA_NON_TEXT, AA_TEXT, contrastRatio, parseThemes, type ThemeName } from "./contrast";
import tokensCss from "./tokens.css?raw";

const themes = parseThemes(tokensCss);
const THEMES: ThemeName[] = ["light", "dark", "warm"];

/** [foreground, background, minimum ratio] */
type Pair = readonly [string, string, number];

const SURFACES = ["bg", "surface", "surface-raised", "subtle"] as const;
const STATUSES = ["success", "warning", "danger", "info"] as const;
const STATES = ["requested", "invoiced", "paid", "performed", "cancelled", "pending"] as const;

const PAIRS: Pair[] = [
  // Body and secondary text on every surface.
  ...SURFACES.flatMap((s): Pair[] => [
    ["fg", s, AA_TEXT],
    ["fg-muted", s, AA_TEXT],
    ["primary-strong", s, AA_TEXT],
  ]),
  ["fg", "accent", AA_TEXT],
  ["fg-muted", "accent", AA_TEXT],
  // Filled controls.
  ["primary-fg", "primary", AA_TEXT],
  ["primary-fg", "primary-hover", AA_TEXT],
  ["primary-strong", "primary-soft", AA_TEXT],
  ["secondary-fg", "secondary", AA_TEXT],
  ["secondary-fg", "secondary-hover", AA_TEXT],
  ["accent-fg", "accent", AA_TEXT],
  // Semantic colors: text on soft fill, text on surfaces, text on solid fill.
  ...STATUSES.flatMap((k): Pair[] => [
    [`${k}-fg`, `${k}-bg`, AA_TEXT],
    [`${k}-fg`, "surface", AA_TEXT],
    [`${k}-contrast`, k, AA_TEXT],
  ]),
  // Service-line state badges.
  ...STATES.map((k): Pair => [`state-${k}-fg`, `state-${k}-bg`, AA_TEXT]),
  // Non-text UI: input borders and focus ring must be perceivable (1.4.11).
  ["border-strong", "surface", AA_NON_TEXT],
  ["border-strong", "bg", AA_NON_TEXT],
  ["ring", "surface", AA_NON_TEXT],
  ["ring", "bg", AA_NON_TEXT],
];

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

describe("contrastRatio", () => {
  it("matches known reference values", () => {
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(contrastRatio("#ffffff", "#ffffff")).toBeCloseTo(1, 5);
    expect(contrastRatio("#777777", "#ffffff")).toBeCloseTo(4.48, 2);
    expect(contrastRatio("#fff", "#000")).toBeCloseTo(21, 5);
  });
});
