/**
 * Contract guard: the report catalog the screens list is the backend's registry
 * (backend/apps/reports/registry.py): same keys, same areas, same permission per report. A
 * report added on one side only, or listed under another code, fails here.
 */
import { describe, expect, it } from "vitest";

import { en } from "@/i18n/resources";

import { REPORT_AREAS, REPORT_CATALOG, REPORT_PERMISSIONS } from "./catalog";

const sources = import.meta.glob<string>("../../../../backend/apps/reports/registry.py", {
  query: "?raw",
  import: "default",
  eager: true,
});
const registry = Object.values(sources)[0];

interface BackendEntry {
  key: string;
  area: string;
  permission: string;
}

function backendEntries(text: string): BackendEntry[] {
  const pattern = /ReportSpec\(\s*"([a-z_]+)",\s*"([a-z_]+)",\s*"([a-z_.]+)"/g;
  return [...text.matchAll(pattern)].map((m) => ({ key: m[1] ?? "", area: m[2] ?? "", permission: m[3] ?? "" }));
}

describe.skipIf(registry === undefined)("report catalog", () => {
  const backend = backendEntries(registry ?? "");

  it("reads the backend registry (the scan itself works)", () => {
    expect(backend.length).toBeGreaterThanOrEqual(14);
  });

  it("lists exactly the backend's reports with the same area and permission", () => {
    const front = REPORT_CATALOG.map(({ key, area, permission }) => ({ key, area, permission }));
    const sort = (a: BackendEntry, b: BackendEntry) => a.key.localeCompare(b.key);
    expect([...front].sort(sort)).toEqual([...backend].sort(sort));
  });

  it("uses only known areas and reports.view_* codes", () => {
    for (const entry of REPORT_CATALOG) {
      expect(REPORT_AREAS).toContain(entry.area);
      expect(entry.permission).toMatch(/^reports\.view_[a-z]+$/);
    }
    expect(REPORT_PERMISSIONS).not.toContain("reports.view_dashboard");
  });

  it("has a title and a description for every report", () => {
    for (const entry of REPORT_CATALOG) {
      expect(en.reports.catalog[entry.key].title).toBeTruthy();
      expect(en.reports.catalog[entry.key].description).toBeTruthy();
    }
  });
});
