/**
 * Perform-first authorization (FEATURES 4.4, invariant 1): a supervisor documents that an
 * unpaid line may be performed before payment; the line then counts as authorized and can be
 * revoked while no work under it has started.
 */
import { expect, test } from "@playwright/test";

import { apiAs, createPatient, createVisit, disposeApiClients, orderLines, tr } from "../../helpers";
import { choose, pageAs, t } from "./kit";

test.describe("@cashier perform first", () => {
  test.describe.configure({ timeout: 120_000 });
  test.afterAll(disposeApiClients);

  test("a supervisor authorizes an unpaid line, then revokes it", async ({ browser }) => {
    const { patient } = await createPatient();
    const { visit } = await createVisit({ patient });
    const [ecg] = await orderLines({ visit, items: [{ service: "PRC-ECG" }] });
    if (!ecg) throw new Error("no line ordered");

    // A cashier does not see the screen.
    const cashier = await pageAs(browser, "cashier");
    await cashier.goto("/cashier");
    await expect(cashier.getByTestId("cashier-nav-performFirst")).toHaveCount(0);
    await cashier.context().close();

    const sup = await pageAs(browser, "cashsup");
    await sup.goto("/cashier/perform-first");
    await sup.getByTestId("cashier-lookup").fill(patient.file_no);
    await sup.locator(`[data-testid="lookup-visit"][data-visit-number="${visit.number}"]`).click();
    const form = sup.getByTestId("perform-first-form");
    await form.getByLabel(/Electrocardiogram/).check();
    await choose(sup, tr("en", "reason.code"), "Emergency");
    await form.getByLabel(tr("en", "reason.note")).fill("Chest pain, ECG before payment");
    // Who asked for the exception is recorded apart from who allowed it (FEATURES 4.4).
    await choose(sup, t("cashier:performFirst.requester"), "Dr. Ahmed Altayeb");
    await form.getByTestId("authorize").click();
    await expect(form.getByText(t("cashier:performFirst.doneTitle"))).toBeVisible();

    const line = (await (await apiAs("cashsup")).get<{ unbilled: { id: number; authorized: boolean }[] }>(
      `/api/billing/visits/${String(visit.id)}`,
    )).unbilled.find((l) => l.id === ecg.id);
    expect(line?.authorized).toBe(true);

    const active = sup.locator("li").filter({ hasText: visit.number }).filter({ hasText: "Electrocardiogram" });
    await expect(active).toBeVisible();
    await expect(active.getByTestId("authorization-requester")).toHaveText(
      t("cashier:performFirst.requestedBy", { name: "Dr. Ahmed Altayeb" }),
    );
    await active.getByRole("button", { name: t("cashier:performFirst.revoke") }).click();
    await sup.getByRole("dialog").getByLabel(tr("en", "reason.note")).fill("Patient paid after all");
    await sup.getByRole("dialog").getByRole("button", { name: t("cashier:performFirst.revoke") }).click();
    await expect(active).toHaveCount(0);
    await sup.context().close();
  });
});
