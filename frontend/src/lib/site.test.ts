import { afterEach, describe, expect, it } from "vitest";

import {
  getSiteConfig,
  isMarketingSite,
  isSignInPath,
  loadSiteConfig,
  rootPublicView,
  setSiteConfig,
  signInPath,
} from "./site";

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
    expect(getSiteConfig()).toEqual({
      marketing: true,
      contactEmail: "a@b.org",
      contactWhatsapp: "249912345678",
      centerSite: false,
      onlineBooking: false,
      patientTracking: false,
      guestBooking: false,
    });
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

describe("center switches (ADR 0028, 0029)", () => {
  it("reads the three switches; only a literal true turns one on", async () => {
    await loadSiteConfig(
      answer({ marketing: false, center_site: true, online_booking: "yes", patient_tracking: true }),
    );
    expect(getSiteConfig()).toMatchObject({ centerSite: true, onlineBooking: false, patientTracking: true });
  });

  it("guest booking is on only with online booking (ADR 0029 D)", async () => {
    await loadSiteConfig(answer({ online_booking: true, guest_booking: true }));
    expect(getSiteConfig().guestBooking).toBe(true);
    await loadSiteConfig(answer({ online_booking: false, guest_booking: true }));
    expect(getSiteConfig().guestBooking).toBe(false);
    await loadSiteConfig(answer({ online_booking: true, guest_booking: false }));
    expect(getSiteConfig().guestBooking).toBe(false);
  });

  it("are off when the server does not answer", async () => {
    setSiteConfig({ centerSite: true, onlineBooking: true, patientTracking: true });
    await loadSiteConfig(() => Promise.reject(new Error("offline")));
    expect(getSiteConfig()).toMatchObject({ centerSite: false, onlineBooking: false, patientTracking: false });
  });

  it("puts the center website ahead of the sales page at the root", () => {
    expect(rootPublicView()).toBeNull();
    setSiteConfig({ marketing: true });
    expect(rootPublicView()).toBe("marketing");
    setSiteConfig({ marketing: true, centerSite: true });
    expect(rootPublicView()).toBe("center");
    setSiteConfig({ centerSite: true });
    expect(rootPublicView()).toBe("center");
  });

  it("leaves the sign-in address to the marketing switch alone", () => {
    setSiteConfig({ centerSite: true });
    expect(signInPath()).toBe("/login");
    setSiteConfig({ centerSite: true, marketing: true });
    expect(signInPath()).toBe("/sign-in");
  });
});
