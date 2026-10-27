import { afterEach, describe, expect, it } from "vitest";

import { getSiteConfig, isMarketingSite, isSignInPath, loadSiteConfig, setSiteConfig, signInPath } from "./site";

afterEach(() => {
  setSiteConfig(null);
});

function answer(body: unknown, ok = true): typeof fetch {
  return () => Promise.resolve({ ok, json: () => Promise.resolve(body) } as Response);
}

describe("site switches (ADR 0027)", () => {
  it("is off by default: /login stays the staff sign-in", () => {
    expect(isMarketingSite()).toBe(false);
    expect(signInPath()).toBe("/login");
  });

  it("sends visitors to /sign-in once the marketing page is on", () => {
    setSiteConfig({ marketing: true });
    expect(signInPath()).toBe("/sign-in");
  });

  it("recognises both sign-in addresses", () => {
    expect(isSignInPath("/login")).toBe(true);
    expect(isSignInPath("/sign-in")).toBe(true);
    expect(isSignInPath("/portal/sign-in")).toBe(false);
  });

  it("reads the server answer, contact values included", async () => {
    await loadSiteConfig(answer({ marketing: true, contact_email: "a@b.org", contact_whatsapp: "249912345678" }));
    expect(getSiteConfig()).toEqual({ marketing: true, contactEmail: "a@b.org", contactWhatsapp: "249912345678" });
  });

  it("only a literal true turns it on", async () => {
    await loadSiteConfig(answer({ marketing: "yes" }));
    expect(isMarketingSite()).toBe(false);
  });

  it("stays off when the server errors or does not answer", async () => {
    setSiteConfig({ marketing: true });
    await loadSiteConfig(answer({}, false));
    expect(isMarketingSite()).toBe(false);
    setSiteConfig({ marketing: true });
    await loadSiteConfig(() => Promise.reject(new Error("offline")));
    expect(isMarketingSite()).toBe(false);
  });
});
