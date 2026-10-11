/**
 * Phase 8 follow-up (FEATURES 11.5, ADR 0018): writing off a rejected amount needs a second
 * person while the center's policy switch is on (the default); the accountant alone is
 * refused. With the switch off, the dialog asks for no approver (ADR 0012's behaviour).
 * Filter with `make e2e E2E_GREP=@followups`.
 */
import { expect, test } from "@playwright/test";

import { E2E_PASSWORD } from "../../fixtures/users";
import { apiAs, disposeApiClients, expectNoHorizontalScroll, snap } from "../../helpers";
import { choose, claimCase, claimLoaded, pageAs, rowAction, t } from "../claims/kit";

test.describe.configure({ mode: "serial", timeout: 180_000 });

interface PolicyOut {
  [key: string]: unknown;
  claims_second_approver: boolean;
  updated_at?: string | null;
  default_pay_first?: boolean;
}

async function setSwitch(on: boolean): Promise<void> {
  const admin = await apiAs("admin");
  const current = await admin.get<PolicyOut>("/api/core/policy");
  const { updated_at: _u, default_pay_first: _d, ...body } = current;
  await admin.put("/api/core/policy", { ...body, claims_second_approver: on });
}

test.afterAll(async () => {
  await setSwitch(true);
  await disposeApiClients();
});

test.describe("@followups @claims second approver", () => {
  test("a write-off needs the manager's credentials", async ({ browser }) => {
    const made = await claimCase({ stage: "answered", services: ["PRC-ECG"], outcomes: ["rejected"] });
    const claim = made.claim;
    if (!claim) throw new Error("claims_case returned no claim");
    const accountant = await apiAs("accountant");
    const lineId = claim.lines[0]?.id;
    if (lineId === undefined) throw new Error("no claim line");
    const refused = await accountant.post<{ code: string }>(
      `/api/claims/batches/${String(claim.id)}/lines/${String(lineId)}/resolve`,
      { resolution: "written_off", reason: "NOT_COVERED" },
      { expect: 409 },
    );
    expect(refused.code).toBe("SECOND_APPROVER_REQUIRED");

    const page = await pageAs(browser, "accountant");
    await page.goto(`/claims/${String(claim.id)}`);
    await claimLoaded(page);
    const line = page.locator("tr").filter({ hasText: made.patient.full_name_en });
    await rowAction(page, line, t("claims:detail.writeOff"));
    const dialog = page.getByTestId("resolve-dialog");
    await choose(page, t("claims:resolve.reason"), "Not covered");
    await dialog.getByLabel(t("approver.username")).fill("accountant");
    await dialog.getByLabel(t("approver.password")).fill(E2E_PASSWORD);
    await dialog.getByTestId("resolve-confirm").click();
    await expect(dialog.getByText(t("errors:SECOND_APPROVER_REQUIRED"))).toBeVisible();
    await expectNoHorizontalScroll(page);
    await snap(page, "followups-claims-second-approver");
    await dialog.getByLabel(t("approver.username")).fill("manager");
    await dialog.getByTestId("resolve-confirm").click();
    await expect(dialog).toBeHidden();
    await expect(line.getByTestId("line-resolution")).toContainText(t("claims:resolution.written_off"));
    await page.context().close();
  });

  test("with the switch off the accountant resolves alone", async ({ browser }) => {
    await setSwitch(false);
    const options = await (await apiAs("accountant")).get<{ second_approver_required: boolean }>("/api/claims/options");
    expect(options.second_approver_required).toBe(false);
    const made = await claimCase({ stage: "answered", services: ["PRC-ECG"], outcomes: ["rejected"] });
    const claim = made.claim;
    if (!claim) throw new Error("claims_case returned no claim");
    const page = await pageAs(browser, "accountant");
    await page.goto(`/claims/${String(claim.id)}`);
    await claimLoaded(page);
    const line = page.locator("tr").filter({ hasText: made.patient.full_name_en });
    await rowAction(page, line, t("claims:detail.rebill"));
    const dialog = page.getByTestId("resolve-dialog");
    await expect(dialog.getByTestId("second-approver")).toHaveCount(0);
    await choose(page, t("claims:resolve.reason"), "Not covered");
    await dialog.getByTestId("resolve-confirm").click();
    await expect(dialog).toBeHidden();
    await expect(line.getByTestId("line-resolution")).toContainText(t("claims:resolution.rebilled"));
    await page.context().close();
  });
});
