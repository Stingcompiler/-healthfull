/**
 * Nav reach: every screen a role is meant to use is reachable from the navigation with the
 * role's default permissions (backend/apps/<app>/permissions.py), and no role gets an entry
 * twice for the same screen. Read from the backend registry, so a change of a default role
 * shows up here.
 */
import { describe, expect, it } from "vitest";

import { visibleNav } from "./nav";

const sources = import.meta.glob<string>(["../../../backend/apps/**/permissions.py", "!../../../backend/**/tests/**"], {
  query: "?raw",
  import: "default",
  eager: true,
});

/** permission code -> default role codes, parsed from the registrations (docstrings removed). */
function defaults(): Map<string, Set<string>> {
  const out = new Map<string, Set<string>>();
  const pattern = /register_permission\(\s*"([a-z_]+\.[a-z_]+)"[\s\S]*?default_roles=\{([^}]*)\}/g;
  for (const raw of Object.values(sources)) {
    const text = raw.replace(/"""[\s\S]*?"""/g, "");
    for (const m of text.matchAll(pattern)) {
      const roles = (m[2] ?? "")
        .split(",")
        .map((t) => t.trim().replace(/^roles\./, ""))
        .filter(Boolean)
        .map((t) => t.toLowerCase());
      out.set(m[1] ?? "", new Set(roles));
    }
  }
  return out;
}

const registry = defaults();

function me(role: string) {
  const permissions = [...registry].filter(([, roles]) => roles.has(role)).map(([code]) => code);
  return { roles: [role], permissions };
}

function paths(role: string): string[] {
  return visibleNav(me(role)).map((item) => item.to);
}

describe.skipIf(registry.size === 0)("navigation reach per role (default permissions)", () => {
  it("parses the registry", () => {
    expect(registry.get("billing.pharmacy_sale")?.has("cashier")).toBe(true);
    expect(registry.get("visits.admit")?.has("receptionist")).toBe(true);
  });

  it("a cashier reaches the walk-in sale", () => {
    expect(paths("cashier")).toContain("/pharmacy/sale");
    expect(paths("cashier")).toContain("/cashier");
  });

  it("a pharmacist reaches the sale through Pharmacy only", () => {
    expect(paths("pharmacist")).toContain("/pharmacy");
    expect(paths("pharmacist")).not.toContain("/pharmacy/sale");
  });

  it("reception reaches the bed board and approved lab results", () => {
    const reception = paths("receptionist");
    expect(reception).toContain("/nursing/beds");
    expect(reception).toContain("/lab/approved-results");
    expect(reception).not.toContain("/nursing");
    expect(reception).not.toContain("/lab");
  });

  it("a nurse reaches sample collection and nursing, not a doctor's clinic", () => {
    const nurse = paths("nurse");
    expect(nurse).toContain("/lab/collect");
    expect(nurse).toContain("/nursing");
    expect(nurse).not.toContain("/clinic");
    expect(nurse).not.toContain("/nursing/beds"); // inside Nursing
  });

  it("a doctor keeps the clinic and reads results there, not in a second lab entry", () => {
    const doctor = paths("doctor");
    expect(doctor).toContain("/clinic");
    expect(doctor).not.toContain("/lab/approved-results");
    expect(doctor).not.toContain("/nursing/beds");
  });

  it("lab staff use the work list, not the ward and desk shortcuts", () => {
    for (const role of ["lab_tech", "lab_supervisor"]) {
      expect(paths(role)).toContain("/lab");
      expect(paths(role)).not.toContain("/lab/collect");
      expect(paths(role)).not.toContain("/lab/approved-results");
    }
  });

  it("the admin sees module entries without the role shortcuts", () => {
    const admin = visibleNav({ roles: ["admin"], permissions: [] }).map((item) => item.to);
    for (const path of ["/pharmacy", "/lab", "/nursing", "/clinic", "/cashier"]) expect(admin).toContain(path);
    for (const path of ["/pharmacy/sale", "/lab/collect", "/lab/approved-results", "/nursing/beds"]) {
      expect(admin).not.toContain(path);
    }
  });
});
