/**
 * WCAG 2.x contrast helpers, used by tests to keep the design tokens AA.
 * https://www.w3.org/TR/WCAG21/#dfn-contrast-ratio
 */

export type Rgb = readonly [number, number, number];

export function parseHex(hex: string): Rgb {
  const match = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.trim());
  if (!match?.[1]) throw new Error(`Not a hex color: ${hex}`);
  let digits = match[1];
  if (digits.length === 3) {
    digits = digits
      .split("")
      .map((d) => d + d)
      .join("");
  }
  const value = Number.parseInt(digits, 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

function channel(c: number): number {
  const s = c / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

export function relativeLuminance([r, g, b]: Rgb): number {
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrastRatio(a: string, b: string): number {
  const la = relativeLuminance(parseHex(a));
  const lb = relativeLuminance(parseHex(b));
  const [hi, lo] = la > lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

/** Minimum ratios from WCAG 2.1 level AA. */
export const AA_TEXT = 4.5;
export const AA_NON_TEXT = 3;

export type ThemeName = "light" | "dark" | "warm";
export type ThemeTokens = Record<string, string>;

/**
 * Extracts `--name: value` declarations per theme from tokens.css.
 * The light theme block is `:root, [data-theme="light"]`.
 */
export function parseThemes(css: string): Record<ThemeName, ThemeTokens> {
  const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const result: Partial<Record<ThemeName, ThemeTokens>> = {};
  const blockRe = /([^{}]+)\{([^{}]*)\}/g;
  for (const block of withoutComments.matchAll(blockRe)) {
    const selector = block[1] ?? "";
    const body = block[2] ?? "";
    const theme = /data-theme="(light|dark|warm)"/.exec(selector)?.[1] as ThemeName | undefined;
    if (!theme) continue;
    const tokens: ThemeTokens = {};
    for (const decl of body.matchAll(/--([\w-]+)\s*:\s*([^;]+);/g)) {
      const name = decl[1];
      const value = decl[2];
      if (name && value) tokens[name] = value.trim();
    }
    result[theme] = tokens;
  }
  if (!result.light || !result.dark || !result.warm) {
    throw new Error("tokens.css must define light, dark and warm themes");
  }
  return result as Record<ThemeName, ThemeTokens>;
}
