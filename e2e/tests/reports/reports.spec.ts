/**
 * Reports (FEATURES 4.5, 12.1, 12.2, 12.4, 12.11): a day of traceable activity (backend fixture
 * `reports_day`: a new doctor, one visit, cash, a discount, a pending transfer) shows its exact
 * totals in the daily revenue report's doctor row, its lines in the exception reports and its
 * transfer among the pending ones; the Excel export is a real workbook with those figures.
 * Every report URL is pinned to the fixture's own day, never "today", so a run across midnight
 * still reads the right rows. Doctors and cashiers are refused the money reports.
 */
import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { ApiError, apiAs, disposeApiClients } from "../../helpers";
import { reportsDay, type ReportsDay } from "../../module-routes/reports";
import { pageAs, reportLoaded, sdg, sectionRows, sectionTotals, t, unzip } from "./kit";

test.describe("@reports revenue and exception reports", () => {
  test.describe.configure({ mode: "serial", timeout: 120_000 });
  test.afterAll(disposeApiClients);

  let made: ReportsDay;
  test.beforeAll(async () => {
    made = await reportsDay();
  });

  test("the doctor's row in daily revenue shows the day's exact totals", async ({ browser }) => {
    const page = await pageAs(browser, "manager");
    await page.goto(`/reports/revenue?from=${made.day}&to=${made.day}`);
    await reportLoaded(page);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(t("reports:catalog.revenue.title"));
    // Pending transfers are a figure of their own, never part of the collected total.
    await expect(page.getByTestId("report-metrics")).toContainText("Transfers pending verification");

    const row = sectionRows(page, "by_doctor").filter({ hasText: made.doctor.name_en });
    await expect(row).toHaveCount(1);
    // Gross 39,000, discount 1,000, net (and patient share) 38,000, nothing credited.
    await expect(row).toContainText(sdg(made.expected.gross));
    await expect(row).toContainText(sdg(made.expected.discount));
    await expect(row).toContainText(sdg(made.expected.net));
    // The section ends with a totals row over every doctor.
    await expect(sectionTotals(page, "by_doctor")).toContainText(t("reports:viewer.total"));

    // The filters show the pinned day; another day has none of it.
    await expect(page.getByLabel(t("reports:filters.dateFrom"), { exact: true })).toHaveValue(made.day);
    await page.goto("/reports/revenue?from=2020-01-01&to=2020-01-01");
    await reportLoaded(page);
    await expect(page.getByTestId("section-by_doctor")).toContainText(t("reports:viewer.emptyTitle"));
    await page.context().close();
  });

  test("exception reports list the visit's paid-not-performed and unbilled lines", async ({ browser }) => {
    const page = await pageAs(browser, "manager");
    await page.goto("/reports/paid_not_performed");
    await reportLoaded(page);
    // The shared database holds every spec's lines: find this visit's with the row search.
    await page.getByTestId("search-lines").fill(made.visit.number);
    const paid = sectionRows(page, "lines").filter({ hasText: made.visit.number });
    // Consultation 15,000, ECG 10,000 less the 1,000 discount, CBC 12,000; the injection was done.
    await expect(paid).toHaveCount(3);
    for (const amount of Object.values(made.expected.paid_not_performed)) {
      await expect(paid.filter({ hasText: sdg(amount) })).toHaveCount(1);
    }

    await page.goto("/reports/requested_not_invoiced");
    await reportLoaded(page);
    await page.getByTestId("search-lines").fill(made.patient.file_no);
    const unbilled = sectionRows(page, "lines").filter({ hasText: made.visit.number });
    await expect(unbilled).toHaveCount(1);
    await expect(unbilled).toContainText(made.patient.file_no);

    await page.goto("/reports/pending_transfers");
    await reportLoaded(page);
    await page.getByTestId("search-transfers").fill(made.transfer.number);
    const transfer = sectionRows(page, "transfers").filter({ hasText: made.transfer.number });
    await expect(transfer).toContainText(sdg(made.expected.pending));
    await page.context().close();
  });

  test("the Excel export downloads a valid workbook with the day's figures", async ({ browser }) => {
    const page = await pageAs(browser, "accountant");
    await page.goto(`/reports/revenue?from=${made.day}&to=${made.day}`);
    await reportLoaded(page);
    const download = page.waitForEvent("download");
    await page.getByTestId("report-excel").click();
    const file = await download;
    expect(file.suggestedFilename()).toBe(`revenue-${made.day}-en.xlsx`);
    const bytes = readFileSync(await file.path());
    expect(bytes.subarray(0, 4).toString("binary")).toBe("PK\u0003\u0004");
    const parts = unzip(bytes);
    expect([...parts.keys()]).toEqual(expect.arrayContaining(["[Content_Types].xml", "xl/workbook.xml"]));
    const sheets = [...parts.entries()]
      .filter(([name]) => name.startsWith("xl/worksheets/") || name === "xl/sharedStrings.xml")
      .map(([, xml]) => xml)
      .join("");
    expect(sheets).toContain("Daily revenue");
    expect(sheets).toContain(made.doctor.name_en);
    // The doctor's net is a number cell, never text.
    expect(sheets).toMatch(/<v>38000(\.0+)?<\/v>/);
    // No formula anywhere in the book.
    expect(sheets).not.toContain("<f>");
    await page.context().close();
  });

  test("the print view shows the report on paper with its letterhead", async ({ browser }) => {
    const page = await pageAs(browser, "manager", 375);
    await page.goto(`/reports/revenue?from=${made.day}&to=${made.day}`);
    await reportLoaded(page);
    // Phones get cards, not a table.
    await expect(page.getByTestId("section-by_doctor").locator('[data-slot="data-table"]')).toHaveAttribute(
      "data-mode",
      "cards",
    );
    await page.getByTestId("report-print").click();
    await expect(page).toHaveURL(new RegExp(`/reports/revenue/print\\?.*from=${made.day}`));
    const doc = page.getByTestId("report-print-document");
    await expect(doc).toContainText(t("reports:catalog.revenue.title"));
    await expect(doc).toContainText(made.doctor.name_en);
    await page.context().close();
  });

  test("doctors and cashiers are refused the money reports", async ({ browser }) => {
    for (const who of ["doctor", "cashier"] as const) {
      const api = await apiAs(who);
      for (const key of ["revenue", "pending_transfers", "paid_not_performed", "dashboard"]) {
        const error = await api.get(`/api/reports/${key}`).catch((e: unknown) => e);
        expect(error, `${who} ${key}`).toBeInstanceOf(ApiError);
        expect((error as ApiError).status).toBe(403);
      }
      const page = await pageAs(browser, who);
      await page.goto("/reports");
      await expect(page.getByText(t("reports:empty.title"))).toBeVisible();
      await expect(page.locator("aside").getByTestId("nav-reports")).toHaveCount(0);
      await page.context().close();
    }
  });
});
