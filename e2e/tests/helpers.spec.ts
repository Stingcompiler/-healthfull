/**
 * The shared API helpers and data factories (e2e/helpers/api.ts) against the real backend
 * and the seeded e2e database. Filter with `make e2e E2E_GREP=@helpers`.
 */
import { expect, test } from "@playwright/test";

import { EXTRA_DOCTORS, USERS, type SeedUser } from "../fixtures/users";
import {
  ApiError,
  apiAs,
  apiOperation,
  approveInvoice,
  closeShift,
  createInvoice,
  createPatient,
  createVisit,
  disposeApiClients,
  factoryMode,
  fixture,
  FixtureError,
  newApiClient,
  openShift,
  orderLines,
  paidVisit,
  pay,
  registerAdapter,
  seededCatalog,
  unregisterAdapter,
  usesApi,
  type InvoiceRef,
} from "../helpers";

// Each fixture call starts a Django process (about two seconds).
test.describe.configure({ timeout: 120_000 });

test.afterAll(async () => {
  // Leave no cashier shift open for later specs.
  await closeShift().catch((error: unknown) => {
    if (!(error instanceof FixtureError && error.code === "SHIFT_NOT_OPEN")) throw error;
  });
  await disposeApiClients();
});

function shares(invoice: InvoiceRef): Record<string, [string, string]> {
  return Object.fromEntries(invoice.lines.map((line) => [line.service, [line.payer_share, line.patient_share]]));
}

test.describe("@helpers api clients", () => {
  test("every seed user gets a logged-in client holding exactly its role", async () => {
    const all = { ...USERS, ...EXTRA_DOCTORS };
    for (const [key, user] of Object.entries(all)) {
      const client = await apiAs(key as SeedUser);
      const me = await client.get<{ username: string; roles: string[] }>("/api/auth/me");
      expect(me.username).toBe(user.username);
      expect(me.roles).toEqual([user.role]);
    }
    // The client is shared per user.
    expect(await apiAs("cashier")).toBe(await apiAs("cashier"));
    expect(await apiAs("cashier_supervisor")).toBe(await apiAs("cashsup"));
  });

  test("unsafe requests carry the CSRF token; without it Django refuses", async () => {
    const nurse = await newApiClient("nurse");
    try {
      const saved = await nurse.patch<{ theme: string; language: string }>("/api/auth/me/preferences", {
        theme: "warm",
        language: "en",
      });
      expect(saved).toMatchObject({ theme: "warm", language: "en" });
      const bare = await nurse.context.patch("/api/auth/me/preferences", { data: { theme: "dark" } });
      expect(bare.status()).toBe(403);
      await nurse.patch("/api/auth/me/preferences", { theme: "light", language: "ar" });
    } finally {
      await nurse.dispose();
    }
  });

  test("errors carry the backend code; operations resolve from openapi.json", async () => {
    const nurse = await apiAs("nurse");
    const failure = await nurse.get("/api/no-such-endpoint").catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(404);
    expect((failure as ApiError).code).toBe("NOT_FOUND");

    expect(apiOperation("auth_update_preferences")).toMatchObject({
      method: "PATCH",
      path: "/api/auth/me/preferences",
    });
    expect(apiOperation("patients_no_such_operation")).toBeUndefined();
    const me = await nurse.call<{ username: string }>("auth_get_me");
    expect(me.username).toBe("nurse");
    await expect(nurse.call("auth_update_preferences", { body: { colour: "red" } })).rejects.toThrow(
      /does not accept body field/,
    );
  });
});

test.describe("@helpers factories", () => {
  test("the seeded catalog is reachable by code", async () => {
    const catalog = await seededCatalog();
    expect(catalog.services["CONS-GEN"]?.cash_price).toBe("15000.00");
    expect(Object.keys(catalog.doctors).sort()).toEqual(["dentist", "doctor", "gynecologist", "pediatrician"]);
    expect(Object.keys(catalog.payers).sort()).toEqual(["AMAN", "NAKHEEL", "RAHMA"]);
    expect(catalog.items["DRG-AMOX500"]?.batches).toHaveLength(2);
    expect(Object.keys(catalog.stores).sort()).toEqual(["MAIN", "PHA"]);
  });

  test("the money cycle: registration to a closed shift", async () => {
    const opened = await openShift({ opening_float: "2000", if_open: "close" });
    expect(opened).toMatchObject({ status: "open", cashier: "cashier", expected_cash: "2000.00" });

    const { patient, coverage } = await createPatient({ payer: "AMAN" });
    expect(patient.file_no).toMatch(/^PT-/);
    expect(coverage?.payer).toBe("AMAN");

    const { visit, lines, queue_entry } = await createVisit({ patient });
    expect(visit).toMatchObject({ payer: "AMAN", doctor: "doctor", department: "GEN", status: "open" });
    expect(lines.map((line) => [line.service, line.state])).toEqual([["CONS-GEN", "requested"]]);
    expect(queue_entry?.ready).toBe(false);

    const ordered = await orderLines({
      visit,
      items: [
        { service: "LAB-CBC" },
        {
          service: "DRG-PARA500",
          prescription: { dose: "1 tablet", dose_quantity: 1, frequency_per_day: 3, duration_days: 5 },
        },
      ],
    });
    expect(ordered.map((line) => [line.service, line.quantity, line.state])).toEqual([
      ["LAB-CBC", 1, "requested"],
      ["DRG-PARA500", 15, "requested"],
    ]);

    const { invoice } = await approveInvoice({ visit });
    expect(invoice.status).toBe("approved");
    // AMAN prices are the cash list x 0.90 and AMAN pays 70% of each line.
    expect(shares(invoice)).toEqual({
      "CONS-GEN": ["9450.00", "4050.00"],
      "LAB-CBC": ["7560.00", "3240.00"],
      "DRG-PARA500": ["472.50", "202.50"],
    });

    const paid = await pay({ invoice });
    expect(paid.payment).toMatchObject({ method: "cash", amount: "7492.50", verification: "confirmed" });
    expect(paid.invoices[0]?.outstanding).toBe("0.00");
    expect(new Set(paid.lines.map((line) => line.state))).toEqual(new Set(["paid"]));
    expect(paid.shift.expected_cash).toBe("9492.50");

    const closed = await closeShift({ counted: "9400", reason: "COUNTING_ERROR" });
    expect(closed).toMatchObject({ status: "closed", variance: "-92.50", counted_cash: "9400.00" });
  });

  test("a paid visit waits ready in the doctor's queue", async () => {
    const made = await paidVisit({ doctor: "pediatrician", patient_fields: { sex: "female", age_years: 6 } });
    expect(made.visit.department).toBe("PED");
    expect(made.queue_entry).toMatchObject({ ready: true, doctor: "pediatrician", status: "waiting" });
    expect(made.invoice?.outstanding).toBe("0.00");
    expect(made.shift?.status).toBe("open");
  });

  test("draft invoices, transfers and partial selections", async () => {
    const { patient } = await createPatient({ payer: "NAKHEEL", sex: "male" });
    const { visit } = await createVisit({ patient, doctor: "dentist" });
    await orderLines({ visit, items: [{ service: "DEN-EXT" }], as: "dentist" });
    const draft = await createInvoice({ visit, services: ["DEN-EXT"] });
    expect(draft.invoice).toMatchObject({ status: "draft", number: null, outstanding: null });
    const approved = await approveInvoice({ invoice: draft.invoice });
    // NAKHEEL leaves a fixed 2,000 copay per line.
    expect(shares(approved.invoice)).toEqual({ "DEN-EXT": ["23000.00", "2000.00"] });
    const transfer = await pay({ invoice: approved.invoice, method: "bank_transfer" });
    expect(transfer.payment).toMatchObject({ verification: "pending", bank: "BOK" });
    expect(transfer.payment.reference).toMatch(/^E2E/);
  });

  test("a refused step throws FixtureError with the backend code; allergies alert", async () => {
    const { patient } = await createPatient();
    const { visit } = await createVisit({ patient, coverage: "cash" });
    const refused = await orderLines({ visit, items: [{ service: "LAB-CBC" }], as: "cashier" }).catch(
      (error: unknown) => error,
    );
    expect(refused).toBeInstanceOf(FixtureError);
    expect((refused as FixtureError).code).toBe("PERMISSION_DENIED");
    expect((refused as FixtureError).details).toEqual({ permission: "orders.create" });
    await expect(fixture("no_such_fixture")).rejects.toMatchObject({ code: "FIXTURE_UNKNOWN" });

    const allergic = await createPatient({ allergies: ["PENICILLIN"] });
    expect(allergic.allergies).toMatchObject([{ drug_class: "PENICILLIN", severity: "severe" }]);
    const clinic = await createVisit({ patient: allergic.patient });
    const amoxicillin = [{ service: "DRG-AMOX500", quantity: 21 }];
    await expect(orderLines({ visit: clinic.visit, items: amoxicillin })).rejects.toMatchObject({
      code: "ALLERGY_ALERT",
    });
    const acknowledged = await orderLines({ visit: clinic.visit, items: amoxicillin, acknowledge_allergies: true });
    expect(acknowledged.map((line) => line.service)).toEqual(["DRG-AMOX500"]);
  });

  test("an adapter sends a factory through the API once its operations exist", async () => {
    test.skip(factoryMode() !== "auto", "adapters are bypassed or required in this mode");
    registerAdapter("openShift", {
      operations: ["auth_get_me"],
      async run(options, api) {
        if (options.till !== undefined) return undefined; // not covered: back to the fixture
        const me = await (await api(options.as ?? "cashier")).call<{ username: string }>("auth_get_me");
        return {
          id: 0,
          number: "API",
          status: "open",
          cashier: me.username,
          till: null,
          opening_float: "0.00",
          expected_cash: "0.00",
          counted_cash: null,
          variance: null,
        };
      },
    });
    registerAdapter("closeShift", {
      operations: ["payments_close_shift_not_built_yet"],
      run: () => Promise.reject(new Error("must not run")),
    });
    try {
      expect(await usesApi("openShift")).toBe(true);
      expect(await openShift()).toMatchObject({ number: "API", cashier: "cashier" });
      const real = await openShift({ till: "T1", if_open: "close" });
      expect(real).toMatchObject({ till: "T1", status: "open" });
      expect(await usesApi("closeShift")).toBe(false);
      expect((await closeShift()).status).toBe("closed");
    } finally {
      unregisterAdapter("openShift");
      unregisterAdapter("closeShift");
    }
  });
});
