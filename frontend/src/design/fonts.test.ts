import { describe, expect, it } from "vitest";

import fontsSource from "./fonts.ts?raw";
import tokensCss from "./tokens.css?raw";

describe("fonts", () => {
  it("bundles one family: Plex Sans Arabic for Arabic and Plex Sans for Latin, no Inter", () => {
    const imports = [...fontsSource.matchAll(/^import "([^"]+)";/gm)].map((m) => m[1] ?? "");
    expect(imports.length).toBeGreaterThan(0);
    for (const spec of imports) {
      expect(spec, spec).toMatch(/^@fontsource\/ibm-plex-sans(-arabic)?\//);
    }
    expect(imports.some((s) => s.startsWith("@fontsource/ibm-plex-sans-arabic/arabic-"))).toBe(true);
    expect(imports.some((s) => s.startsWith("@fontsource/ibm-plex-sans/latin-"))).toBe(true);
  });

  it("the generated stack lists Arabic first, then Latin, and never Inter", () => {
    const stack = /--font-ui:\s*([^;]+);/.exec(tokensCss)?.[1] ?? "";
    expect(stack.startsWith('"IBM Plex Sans Arabic", "IBM Plex Sans"')).toBe(true);
    expect(stack.toLowerCase()).not.toContain("inter");
  });
});
