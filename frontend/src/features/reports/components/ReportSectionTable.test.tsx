import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { setViewportWidth } from "@/test/match-media";
import { renderWithProviders } from "@/test/render";

import type { ReportSection } from "../types";
import { ReportSectionTable } from "./ReportSectionTable";

const section: ReportSection = {
  key: "by_department",
  label: { ar: "حسب القسم", en: "By department" },
  truncated: false,
  columns: [
    { key: "department", kind: "name", label: { ar: "القسم", en: "Department" } },
    { key: "count", kind: "int", label: { ar: "العدد", en: "Count" } },
    { key: "net", kind: "money", label: { ar: "الصافي", en: "Net" } },
    { key: "age", kind: "days", label: { ar: "العمر", en: "Age" } },
  ],
  rows: [
    { department: { ar: "المعمل", en: "Laboratory" }, count: 3, net: "20000.00", age: 2 },
    { department: { ar: "العيادة", en: "Clinic" }, count: 1, net: "-1500.00", age: null },
  ],
  totals: { count: 4, net: "18500.00" },
};

describe("ReportSectionTable", () => {
  afterEach(() => {
    setViewportWidth(1280);
  });

  it("renders a table with typed cells and a totals row on desktop", async () => {
    setViewportWidth(1280);
    await renderWithProviders(<ReportSectionTable section={section} maxRows={2000} />);
    const table = screen.getByRole("table", { name: "By department" });
    expect(within(table).getByText("Laboratory")).toBeInTheDocument();
    expect(within(table).getByText("2 days")).toBeInTheDocument();
    const footer = table.querySelector("tfoot");
    expect(footer).not.toBeNull();
    expect(footer?.textContent).toContain("Total");
    expect(footer?.textContent).toContain("18,500.00");
  });

  it("renders cards and a totals card on a phone, in Arabic", async () => {
    setViewportWidth(375);
    await renderWithProviders(<ReportSectionTable section={section} maxRows={2000} />, { language: "ar" });
    const list = screen.getByRole("list", { name: "حسب القسم" });
    expect(within(list).getByText("المعمل")).toBeInTheDocument();
    const totals = list.querySelector('[data-slot="data-table-totals"]');
    expect(totals?.textContent).toContain("الإجمالي");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("says when rows were cut", async () => {
    await renderWithProviders(<ReportSectionTable section={{ ...section, truncated: true }} maxRows={2000} />);
    expect(screen.getByText(/Only the first 2000 rows/)).toBeInTheDocument();
  });
});
