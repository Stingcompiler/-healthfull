import { describe, expect, it } from "vitest";

import { ALL_NAV, visibleNav } from "./nav";
import { safeRedirectTarget } from "./guards";
import { router } from "./router";

const paths = new Set(Object.keys(router.routesByPath).map((p) => (p.length > 1 ? p.replace(/\/$/, "") : p)));

describe("route tree", () => {
  it("pre-registers every feature module", () => {
    for (const path of [
      "/",
      "/login",
      "/change-password",
      "/patients",
      "/queue",
      "/appointments",
      "/clinic",
      "/cashier",
      "/pharmacy",
      "/lab",
      "/nursing",
      "/claims",
      "/reports",
      "/administration",
      "/administration/users",
      "/administration/roles",
      "/administration/catalog",
      "/administration/price-lists",
      "/administration/payers",
      "/administration/settings",
      "/administration/imports",
      "/administration/system",
      "/design",
      "/portal",
      "/display/queue",
    ]) {
      expect(paths, path).toContain(path);
    }
  });

  it("never mounts SPA pages under /admin or /api (proxied to Django)", () => {
    for (const p of paths) expect(p).not.toMatch(/^\/(admin|api|static)(\/|$)/);
  });

  it("every nav entry points at a registered route", () => {
    for (const item of ALL_NAV) expect(paths, item.id).toContain(item.to);
  });

  it("nav ids are unique", () => {
    const ids = ALL_NAV.map((n) => n.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("visibleNav", () => {
  const ids = (roles: string[], permissions: string[]) => visibleNav({ roles, permissions }).map((n) => n.id);

  it("shows everything to the admin role", () => {
    expect(ids(["admin"], [])).toEqual(ALL_NAV.map((n) => n.id));
  });

  it("filters by permission for other roles", () => {
    const reception = ids(["receptionist"], ["patients.view", "visits.view_queue"]);
    expect(reception).toContain("dashboard");
    expect(reception).toContain("patients");
    expect(reception).toContain("queue");
    expect(reception).not.toContain("cashier");
    expect(reception).not.toContain("admin");
  });

  it("shows Administration when any admin section is granted", () => {
    expect(ids(["manager"], ["ops.view_status"])).toContain("admin");
  });

  it("shows nothing but public entries when logged out", () => {
    expect(visibleNav(null)).toEqual([]);
  });
});

describe("safeRedirectTarget", () => {
  it("accepts same-app absolute paths", () => {
    expect(safeRedirectTarget("/patients?q=ali")).toBe("/patients?q=ali");
  });

  it.each(["//evil.example/x", "https://evil.example", "/\\evil", "patients", "/login?redirect=/", 42, undefined])(
    "rejects %s",
    (target) => {
      expect(safeRedirectTarget(target)).toBeNull();
    },
  );
});
