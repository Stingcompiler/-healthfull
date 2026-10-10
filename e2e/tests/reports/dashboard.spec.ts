/**
 * Manager dashboard (FEATURES 12.10): after a day of activity (backend fixture `reports_day`)
 * the phone dashboard's figures are the reports' own: confirmed collection equals the daily
 * revenue report's collected total for the dashboard's date, pending transfers equal the
 * pending-transfers report (never part of the collection), net revenue equals the revenue
 * report. The dashboard date comes from the dashboard itself, so midnight cannot split the
 * comparison. Staff without the dashboard code see their modules instead.
 */
import { expect, test, type Page } from "@playwright/test";

import { apiAs, disposeApiClients } from "../../helpers";
import { reportsDay } from "../../module-routes/reports";
import { amountOf, pageAs, t } from "./kit";

interface Metric {
  key: string;
  value: string | number | null;
}

interface ReportBody {
  metrics: Metric[];
}

function metric(body: { metrics: Metric[] }, key: string): string {
  return String(body.metrics.find((m) => m.key === key)?.value ?? "");
}

/** The value of the KPI card with this label. */
function kpi(page: Page, label: string) {
  return page.locator('[data-slot="kpi-card"]').filter({ hasText: label }).locator('[data-slot="money"]').first();
}

test.describe("@reports manager dashboard", () => {
  test.describe.configure({ timeout: 120_000 });
  test.afterAll(disposeApiClients);

  test("the phone dashboard's KPIs match the reports", async ({ browser }) => {
    const made = await reportsDay();
    const manager = await apiAs("manager");
    const dashboard = await manager.get<{ date: string; metrics: Metric[] }>("/api/reports/dashboard");
    const day = dashboard.date;
    const revenue = await manager.get<ReportBody>(`/api/reports/revenue?date_from=${day}&date_to=${day}`);
    const pending = await manager.get<ReportBody>("/api/reports/pending_transfers");

    // The API's own figures agree first.
    expect(metric(dashboard, "collected_today")).toBe(metric(revenue, "collected"));
    expect(metric(dashboard, "net_revenue_today")).toBe(metric(revenue, "net_revenue"));
    expect(metric(dashboard, "pending_transfers")).toBe(metric(pending, "pending_total"));
    const ofTheDay = await manager.get<ReportBody>(`/api/reports/revenue?date_from=${made.day}&date_to=${made.day}`);
    expect(Number(metric(ofTheDay, "pending_transfers"))).toBeGreaterThanOrEqual(Number(made.expected.pending));

    const page = await pageAs(browser, "manager", 375);
    await page.goto("/");
    await expect(page.getByTestId("manager-dashboard")).toBeVisible();
    await expect(page.getByTestId("chart-collections")).toBeVisible();
    await expect(page.getByTestId("chart-departments")).toBeVisible();

    await expect.poll(() => amountOf(kpi(page, t("dashboard:kpi.collectedToday")))).toBe(metric(revenue, "collected"));
    await expect.poll(() => amountOf(kpi(page, t("dashboard:kpi.pendingTransfers")))).toBe(
      metric(pending, "pending_total"),
    );
    await expect.poll(() => amountOf(kpi(page, t("dashboard:kpi.netRevenueToday")))).toBe(
      metric(revenue, "net_revenue"),
    );
    // Pending money is never inside the collected figure.
    expect(Number(metric(revenue, "collected"))).toBe(
      Number(metric(revenue, "cash")) + Number(metric(revenue, "bank_confirmed")),
    );
    await expect(page.getByRole("heading", { name: t("dashboard:alerts.title") })).toBeVisible();
    await page.context().close();
  });

  test("staff without the dashboard code see their modules", async ({ browser }) => {
    const page = await pageAs(browser, "reception", 375);
    await page.goto("/");
    await expect(page.getByTestId("staff-modules")).toBeVisible();
    await expect(page.getByTestId("staff-modules")).toContainText(t("nav:items.patients"));
    await expect(page.getByTestId("manager-dashboard")).toHaveCount(0);
    await page.context().close();
  });
});
