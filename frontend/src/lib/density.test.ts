import { describe, expect, it } from "vitest";

import { densityAttribute, densityForPath } from "./density";
import tokensCss from "../design/tokens.css?raw";

describe("density", () => {
  it("the cashier and the pharmacy run compact, every other staff route the default", () => {
    expect(densityForPath("/cashier")).toBe("compact");
    expect(densityForPath("/cashier/shift")).toBe("compact");
    expect(densityForPath("/pharmacy/items/3")).toBe("compact");
    expect(densityForPath("/")).toBe("default");
    expect(densityForPath("/clinic/visits/4")).toBe("default");
    // A prefix is not an area: "/cashiers-report" is not the cashier.
    expect(densityForPath("/cashiers-report")).toBe("default");
  });

  it("the default mode sets no attribute", () => {
    expect(densityAttribute("default")).toBeUndefined();
    expect(densityAttribute("compact")).toBe("compact");
    expect(densityAttribute("comfortable")).toBe("comfortable");
  });

  it("tokens.css defines every density token for every mode (from density.tokens.json)", () => {
    for (const selector of [":root", '[data-density="compact"]', '[data-density="comfortable"]']) {
      const block = new RegExp(`${selector.replace(/[[\]"]/g, "\\$&")} \\{([^}]*)\\}`).exec(
        tokensCss.slice(tokensCss.indexOf("/* density: default */")),
      );
      expect(block, selector).not.toBeNull();
      for (const token of ["d-row", "d-pad", "d-gap", "d-card-pad", "d-font"]) {
        expect(block?.[1], `${selector} --${token}`).toContain(`--${token}:`);
      }
    }
  });

  it("compact is denser than default, which is denser than comfortable", () => {
    const px = (mode: string, token: string) => {
      const start = tokensCss.indexOf(`/* density: ${mode} */`);
      const block = tokensCss.slice(start, tokensCss.indexOf("}", start));
      return Number(new RegExp(`--${token}: (\\d+)px`).exec(block)?.[1]);
    };
    for (const token of ["d-row", "d-pad", "d-gap", "d-card-pad", "d-font"]) {
      expect(px("compact", token), token).toBeLessThan(px("default", token));
      expect(px("default", token), token).toBeLessThan(px("comfortable", token));
    }
  });
});
