/**
 * Stock counts and adjustments (FEATURES 8.6, 8.7; invariant 5): a count variance is posted
 * as a count correction by a manager, and an adjustment that would take a batch below zero
 * is refused with a translated error.
 */
import { expect, test } from "@playwright/test";

import { apiAs, disposeApiClients, seededCatalog, tr } from "../../helpers";
import { choose, pageAs, t } from "./kit";

interface CountLine {
  batch_id: number;
  batch_no: string;
  book_qty: number;
  counted_qty: number | null;
  variance: number | null;
}

interface Count {
  id: number;
  status: string;
  lines: CountLine[];
}

test.describe("@pharmacy stock", () => {
  test.describe.configure({ timeout: 240_000 });
  test.afterAll(disposeApiClients);

  test("count variance posts an adjustment", async ({ browser }) => {
    const catalog = await seededCatalog();
    const main = catalog.stores.MAIN;
    if (main === undefined) throw new Error("seeded MAIN store is missing");
    const pharmacist = await apiAs("pharmacist");
    // A count left open by an earlier run on this database would block a new one.
    const open = await pharmacist.get<{
      items: { id: number; store: { id: number } }[];
    }>("/api/pharmacy/counts?status=open&page_size=100");
    for (const c of open.items.filter((c) => c.store.id === main)) {
      await pharmacist.post(`/api/pharmacy/counts/${String(c.id)}/cancel`);
    }

    const page = await pageAs(browser, "pharmacist");
    await page.goto("/pharmacy/counts");
    await page.getByTestId("count-new").click();
    const dialog = page.getByTestId("count-dialog");
    await choose(dialog, t("pharmacy:counts.columns.store"), "Main store");
    await page.getByTestId("count-start").click();
    await expect(page).toHaveURL(/\/pharmacy\/counts\/\d+$/);
    const countId = Number(new URL(page.url()).pathname.split("/").pop());
    const count = await pharmacist.get<Count>(`/api/pharmacy/counts/${String(countId)}`);
    expect(count.lines.length).toBeGreaterThan(0);

    // Everything matches the book except one batch, where one unit is missing.
    const short = count.lines[0];
    if (!short) throw new Error("the count has no lines");
    for (const line of count.lines) {
      const row = page.locator(`[data-testid="count-line"][data-batch-no="${line.batch_no}"]`);
      const counted = line === short ? line.book_qty - 1 : line.book_qty;
      await row.getByTestId("count-input").fill(String(counted));
      await row.getByTestId("count-save").click();
      await expect(row.getByTestId("count-variance")).toBeVisible();
    }
    const shortRow = page.locator(`[data-testid="count-line"][data-batch-no="${short.batch_no}"]`);
    await expect(shortRow.getByTestId("count-variance")).toContainText("-1");
    // A pharmacist counts; a manager posts.
    await expect(page.getByTestId("count-post")).toHaveCount(0);
    await page.context().close();

    const manager = await pageAs(browser, "manager");
    await manager.goto(`/pharmacy/counts/${String(countId)}`);
    await manager.getByTestId("count-post").click();
    await manager
      .getByRole("alertdialog")
      .getByRole("button", { name: t("pharmacy:count.post") })
      .click();
    await expect(manager.getByTestId("count-summary").locator('[data-status="posted"]')).toBeVisible();
    await manager.context().close();

    // The variance became a count correction on that batch's stock card.
    const posted = await pharmacist.get<Count>(`/api/pharmacy/counts/${String(countId)}`);
    expect(posted.status).toBe("posted");
    const balances = await pharmacist.get<{ batch_id: number; on_hand: number }[]>(
      `/api/pharmacy/stores/${String(main)}/batches?q=${encodeURIComponent(short.batch_no)}`,
    );
    const after = balances.find((b) => b.batch_id === short.batch_id);
    expect(after?.on_hand ?? 0).toBe(short.book_qty - 1);
  });

  test("stock never goes negative: the error is shown", async ({ browser }) => {
    const page = await pageAs(browser, "pharmacist");
    await page.goto("/pharmacy/adjustments");
    await page.getByTestId("adjustment-new").click();
    const dialog = page.getByTestId("adjustment-dialog");
    await choose(dialog, t("pharmacy:adjustments.fields.store"), "Outpatient pharmacy");
    await choose(dialog, t("pharmacy:adjustments.fields.reason"), "Damaged");
    await dialog.getByTestId("adjustment-batch").fill("Ibuprofen");
    await dialog.getByTestId("adjustment-batch-results").getByRole("button").first().click();
    await dialog.getByTestId("adjustment-qty").fill("999999");
    await dialog.getByTestId("adjustment-save").click();
    const alert = dialog.getByRole("alert").filter({ hasText: tr("en", "errors:title") });
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(tr("en", "errors:STOCK_INSUFFICIENT").split(".")[0] ?? "");
    await page.context().close();
  });
});
