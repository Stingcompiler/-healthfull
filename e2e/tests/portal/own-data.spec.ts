/**
 * A patient sees only their own records (ADR 0016): another patient's result answers 404, and
 * a result still waiting for the lab supervisor never shows (FEATURES 9.4).
 */
import { expect, test } from "@playwright/test";

import { phonePage, portalPatient, signInPortal, t } from "./kit";

test.describe("@portal own data", () => {
  test.describe.configure({ timeout: 120_000 });

  test("sees only own data; another patient's result answers 404", async ({ browser }) => {
    const [mine, theirs] = await Promise.all([portalPatient(), portalPatient()]);
    const page = await phonePage(browser);
    await signInPortal(page, mine);
    const api = page.context().request;

    const results = (await (await api.get("/api/portal/results")).json()) as { line_id: number }[];
    expect(results.map((r) => r.line_id)).toEqual([mine.approved_line]);
    for (const path of [
      `/api/portal/results/${String(theirs.approved_line)}`,
      `/api/portal/invoices/${String(theirs.invoice.id)}`,
      `/api/portal/receipts/${String(theirs.payment.id)}`,
    ]) {
      const response = await api.get(path);
      expect(response.status(), path).toBe(404);
      expect(((await response.json()) as { code: string }).code).toBe("NOT_FOUND");
    }

    // The screen says the same: nothing to see.
    await page.goto(`/portal/results/${String(theirs.approved_line)}`);
    await expect(page.getByText(t("errors:NOT_FOUND")).first()).toBeVisible();
    await expect(page.getByTestId("result-values")).toHaveCount(0);

    await page.goto("/portal/invoices");
    await expect(page.getByTestId("invoice-row")).toHaveCount(1);
    await expect(page.getByTestId("invoice-row")).toContainText(mine.invoice.number);
  });

  test("views an approved result while an unapproved one stays hidden", async ({ browser }) => {
    const mine = await portalPatient();
    const page = await phonePage(browser);
    await signInPortal(page, mine);

    await page.goto("/portal/results");
    const rows = page.getByTestId("result-row");
    await expect(rows).toHaveCount(1);
    await expect(rows.first()).toHaveAttribute("data-line", String(mine.approved_line));
    expect((await page.context().request.get(`/api/portal/results/${String(mine.draft_line)}`)).status()).toBe(404);

    await rows.first().click();
    const values = page.getByTestId("result-values");
    await expect(values).toBeVisible();
    await expect(values.locator("li")).toHaveCount(3);
    await expect(page.getByTestId("result-report")).toContainText(mine.patient.file_no);
    await page.getByTestId("result-print").click(); // window.print is stubbed: it must not throw
  });
});
