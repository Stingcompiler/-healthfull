/**
 * Phase 8 follow-up (FEATURES 8.4, ADR 0018): units a patient brings back are returned to
 * stock from the pharmacy's returns screen. A paid line needs a second person's credentials;
 * the money is refunded at the cashier, never here. Units given under a perform-first
 * authorization come back on the pharmacist's reason alone.
 * Filter with `make e2e E2E_GREP=@followups`.
 */
import { expect, test, type Page } from "@playwright/test";

import { ANONYMOUS_STATE } from "../../fixtures/state";
import { E2E_PASSWORD } from "../../fixtures/users";
import {
  apiAs,
  closeShift,
  disposeApiClients,
  expectNoHorizontalScroll,
  fixture,
  FixtureError,
  login,
  setPrefs,
  snap,
  tr,
  trackConsoleErrors,
} from "../../helpers";

test.describe.configure({ timeout: 180_000 });
test.use({ storageState: ANONYMOUS_STATE });

test.afterAll(async () => {
  await closeShift().catch((error: unknown) => {
    if (!(error instanceof FixtureError && error.code === "SHIFT_NOT_OPEN"))
      throw error;
  });
  await disposeApiClients();
});

interface Dispensed {
  patient: { file_no: string };
  lines: { id: number; qty_base: number }[];
}

interface ReturnsPage {
  items: {
    lines: {
      id: number;
      returned: number;
      returnable: number;
      needs_approver: boolean;
    }[];
  }[];
}

async function choose(
  page: Page,
  label: string,
  option: string,
): Promise<void> {
  await page.getByRole("combobox", { name: label }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

test.describe("@followups @pharmacy dispense returns", () => {
  test("paid units come back into stock on a supervisor's approval", async ({
    page,
  }) => {
    const logged = trackConsoleErrors(page, { allowAnonymousMe: true });
    const made = await fixture<Dispensed>("pharmacy_dispensed", {
      patient_fields: { full_name_en: "Nafisa Abdelrahim Osman Ali" },
    });
    const line = made.lines[0];
    if (!line) throw new Error("nothing dispensed");

    await page.setViewportSize({ width: 375, height: 812 });
    await login(page, "pharmacist");
    await setPrefs(page, { theme: "light", lang: "en" });
    await page.goto("/pharmacy/returns");
    await page
      .getByLabel(tr("en", "pharmacy:returns.search"))
      .fill(made.patient.file_no);
    const row = page.locator(
      `[data-testid="returnable-line"][data-line-id="${String(line.id)}"]`,
    );
    await expect(row).toContainText(tr("en", "pharmacy:returns.paidBadge"));
    await row.getByTestId("return-open").click();
    const dialog = page.getByTestId("return-dialog");
    await expect(dialog.getByTestId("return-returnable")).toContainText(
      String(line.qty_base),
    );
    await dialog.getByLabel(tr("en", "pharmacy:returns.quantity")).fill("3");
    await choose(page, tr("en", "reason.code"), "Returned by the patient");
    await dialog.getByLabel(tr("en", "approver.username")).fill("pharmacist");
    await dialog.getByLabel(tr("en", "approver.password")).fill(E2E_PASSWORD);
    await dialog.getByTestId("return-confirm").click();
    await expect(
      dialog.getByText(tr("en", "errors:SECOND_APPROVER_REQUIRED")),
    ).toBeVisible();
    await expectNoHorizontalScroll(page);
    await snap(page, "followups-dispense-return");

    await dialog.getByLabel(tr("en", "approver.username")).fill("cashsup");
    await dialog.getByTestId("return-confirm").click();
    await expect(dialog).toBeHidden();
    await expect(row.getByTestId("line-returned")).toContainText("3");

    const pharmacist = await apiAs("pharmacist");
    const after = await pharmacist.get<ReturnsPage>(
      `/api/pharmacy/returns?q=${made.patient.file_no}`,
    );
    const back = after.items
      .flatMap((d) => d.lines)
      .find((l) => l.id === line.id);
    expect(back?.returned).toBe(3);
    expect(back?.returnable).toBe(line.qty_base - 3);
    // The refused self-approval is a documented 409, which Chrome logs as a failed load.
    expect(logged.errors().filter((e) => !e.includes("status of 409"))).toEqual([]);
  });

  test("units given under a perform-first authorization need no second person", async ({
    page,
  }) => {
    const made = await fixture<Dispensed>("pharmacy_dispensed", {
      pay: false,
      patient_fields: { full_name_en: "Omer Siddig Elamin Khalid" },
    });
    const line = made.lines[0];
    if (!line) throw new Error("nothing dispensed");
    await page.setViewportSize({ width: 1280, height: 800 });
    await login(page, "pharmacist");
    await setPrefs(page, { theme: "warm", lang: "ar" });
    await page.goto("/pharmacy/returns");
    await page
      .getByLabel(tr("ar", "pharmacy:returns.search"))
      .fill(made.patient.file_no);
    const row = page.locator(
      `[data-testid="returnable-line"][data-line-id="${String(line.id)}"]`,
    );
    await row.getByTestId("return-open").click();
    const dialog = page.getByTestId("return-dialog");
    await expect(dialog.getByTestId("second-approver")).toHaveCount(0);
    await dialog.getByLabel(tr("ar", "pharmacy:returns.quantity")).fill("2");
    await choose(page, tr("ar", "reason.code"), "صُرف بالخطأ");
    await dialog.getByTestId("return-confirm").click();
    await expect(dialog).toBeHidden();
    await expect(row.getByTestId("line-returned")).toContainText("2");
    await expectNoHorizontalScroll(page);
  });

  test("a role without dispensing cannot return units", async () => {
    const made = await fixture<Dispensed>("pharmacy_dispensed", {});
    const line = made.lines[0];
    if (!line) throw new Error("nothing dispensed");
    const cashsup = await apiAs("cashsup");
    const refused = await cashsup.post<{ code: string }>(
      `/api/pharmacy/dispense-lines/${String(line.id)}/returns`,
      { quantity: 1, reason_code: "PATIENT_RETURNED" },
      { expect: 403 },
    );
    expect(refused.code).toBe("PERMISSION_DENIED");
  });
});
