/**
 * Doctors never see billing (FEATURES 3.8, 14.3; ARCHITECTURE 4.10): no billing or payment
 * permission, 403 from every billing and payments operation, no cashier entry in the menu, and
 * no price in anything the clinic API answers. Filter with `make e2e E2E_GREP=@clinic`.
 */
import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { FRONTEND_DIR } from "../../env";
import { ANONYMOUS_STATE } from "../../fixtures/state";
import {
  apiAs,
  disposeApiClients,
  login,
  paidVisit,
  setPrefs,
} from "../../helpers";

test.describe.configure({ timeout: 120_000 });
test.use({ storageState: ANONYMOUS_STATE });
test.afterAll(disposeApiClients);

interface OpenApi {
  paths: Record<string, Record<string, { operationId?: string }>>;
}

/** Every billing and payments operation of the API contract, except the module pings. */
function moneyOperations(): { method: string; url: string; id: string }[] {
  const spec = JSON.parse(
    readFileSync(path.join(FRONTEND_DIR, "openapi.json"), "utf8"),
  ) as OpenApi;
  const out: { method: string; url: string; id: string }[] = [];
  for (const [route, item] of Object.entries(spec.paths)) {
    if (!/^\/api\/(billing|payments)\//.test(route) || route.endsWith("/ping"))
      continue;
    for (const [method, op] of Object.entries(item)) {
      out.push({
        method: method.toUpperCase(),
        url: route.replace(/\{[^}]+\}/g, "1"),
        id: op.operationId ?? route,
      });
    }
  }
  return out;
}

const PRICE_KEY = /price|amount|share|gross|discount|total|balance|invoice/i;

function priceKeys(value: unknown, found: string[] = []): string[] {
  if (Array.isArray(value)) for (const v of value) priceKeys(v, found);
  else if (value && typeof value === "object") {
    for (const [key, inner] of Object.entries(value)) {
      if (PRICE_KEY.test(key)) found.push(key);
      priceKeys(inner, found);
    }
  }
  return found;
}

test.describe("@clinic doctor has no billing access", () => {
  test("the doctor holds no billing or payment permission", async () => {
    const doctor = await apiAs("doctor");
    const me = await doctor.get<{ permissions: string[] }>("/api/auth/me");
    expect(
      me.permissions.filter((p) => /^(billing|payments|claims)\./.test(p)),
    ).toEqual([]);
    expect(me.permissions).toEqual(
      expect.arrayContaining(["clinical.view", "orders.create"]),
    );
  });

  // The billing and payments routers have only their pings until the cashier module lands
  // (wave a, feat/a-cashier); an empty list must never pass silently.
  test.fixme("every billing and payments operation answers 403 to a doctor", async () => {
    const doctor = await apiAs("doctor");
    const operations = moneyOperations();
    expect(
      operations.length,
      "billing and payments operations in the API contract",
    ).toBeGreaterThan(0);
    for (const op of operations) {
      const response = await doctor.send(
        op.method,
        op.url,
        op.method === "GET" ? {} : { data: {} },
      );
      expect(response.status(), `${op.id} ${op.method} ${op.url}`).toBe(403);
      const body = (await response.json()) as { code: string };
      expect(body.code, op.id).toBe("PERMISSION_DENIED");
    }
  });

  test("nothing the doctor reads about a visit carries a price", async () => {
    const ready = await paidVisit({ doctor: "dentist" });
    const doctor = await apiAs("dentist");
    const visitId = ready.visit.id;
    const patientId = ready.patient.id;
    await doctor.post(`/api/orders/visits/${String(visitId)}/lines`, {
      items: [
        {
          service_id: (
            await doctor.get<{ id: number }[]>("/api/orders/catalog?q=LAB-CBC")
          )[0]?.id,
        },
      ],
    });
    for (const url of [
      "/api/clinical/worklist",
      `/api/clinical/visits/${String(visitId)}/workspace`,
      `/api/clinical/patients/${String(patientId)}/summary`,
      `/api/clinical/patients/${String(patientId)}/history`,
      `/api/orders/visits/${String(visitId)}/lines`,
      "/api/orders/catalog?q=LAB",
    ]) {
      expect(priceKeys(await doctor.get(url)), url).toEqual([]);
    }
    // Leave the dentist's queue empty for later specs.
    const rows = await doctor.get<{ id: number; status: string }[]>(
      "/api/clinical/worklist",
    );
    for (const row of rows.filter((r) => r.status === "waiting")) {
      for (const action of ["call", "start", "complete"]) {
        await doctor.post(`/api/clinical/worklist/${String(row.id)}/action`, {
          action,
        });
      }
    }
  });

  test("the cashier screen is not in the doctor's menu and its data stays closed", async ({
    page,
  }) => {
    const leaked: string[] = [];
    page.on("response", (response) => {
      const url = new URL(response.url());
      if (
        !/^\/api\/(billing|payments)\//.test(url.pathname) ||
        url.pathname.endsWith("/ping")
      )
        return;
      if (response.ok())
        leaked.push(`${url.pathname} ${String(response.status())}`);
    });
    await login(page, "doctor");
    await setPrefs(page, { theme: "light", lang: "en" });
    await expect(page.getByTestId("nav-clinic").first()).toBeAttached();
    await expect(page.getByTestId("nav-cashier")).toHaveCount(0);
    await page.goto("/cashier");
    await page.waitForLoadState("networkidle");
    expect(leaked, "billing or payment data answered to a doctor").toEqual([]);
  });
});
