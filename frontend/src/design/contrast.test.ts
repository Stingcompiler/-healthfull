import { describe, expect, it } from "vitest";

import { AA_NON_TEXT, AA_TEXT, blend, contrastRatio, parseThemes, type ThemeName } from "./contrast";
import tokensCss from "./tokens.css?raw";

/** Every component source, to check the classes actually used (not just the tokens). */
const SOURCES = import.meta.glob<string>(["../**/*.tsx", "!../**/*.test.tsx"], {
  query: "?raw",
  import: "default",
  eager: true,
});

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
  // Non-text UI (1.4.11). Control borders and the off switch track use --border-strong at full
  // strength, on every surface a control can sit on (popovers are surface-raised).
  ...SURFACES.map((s): Pair => ["border-strong", s, AA_NON_TEXT]),
  // White switch thumb on the off track.
  ["surface", "border-strong", AA_NON_TEXT],
  // Focus outline (focus-ring utilities) on every surface, on the active nav item
  // (primary-soft), on hovered rows (accent) and around filled buttons.
  ...SURFACES.map((s): Pair => ["ring", s, AA_NON_TEXT]),
  ["ring", "primary-soft", AA_NON_TEXT],
  ["ring", "accent", AA_NON_TEXT],
  // Highlighted menu / select / command item: the start-edge bar in --ring must stand out
  // from the popover and from the item's own tint; its text stays AA on the tint.
  ["ring", "surface-raised", AA_NON_TEXT],
  ["primary-strong", "primary-soft", AA_TEXT],
  // Destructive menu item highlight.
  ["danger", "danger-bg", AA_NON_TEXT],
  ["danger-fg", "danger-bg", AA_TEXT],
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
