import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/errors";

import { draftFromService, draftsFromOrderSet, toFavorite, toOrderItem } from "./draft";
import { allergyConflict, lineBadgeState, toPatientCard } from "./lib";
import type { OrderableService, OrderSet, PatientBrief } from "./types";

const amoxicillin: OrderableService = {
  id: 7,
  code: "DRG-AMOX500",
  kind: "drug",
  name_ar: "أموكسيسيلين 500",
  name_en: "Amoxicillin 500",
  department_code: "PHA",
  drug: {
    generic_name: "Amoxicillin",
    brand_name: "",
    form: "capsule",
    strength: "500 mg",
    base_unit_code: "capsule",
    base_unit_name_ar: "كبسولة",
    base_unit_name_en: "capsule",
    classes: [{ code: "PENICILLIN", name_ar: "البنسلينات", name_en: "Penicillins" }],
  },
};

const cbc: OrderableService = {
  id: 3,
  code: "LAB-CBC",
  kind: "lab",
  name_ar: "صورة دم كاملة",
  name_en: "Complete blood count",
  department_code: "LAB",
  drug: null,
};

describe("order drafts", () => {
  it("sends a lab test as one unit and leaves a drug's quantity to the server", () => {
    expect(toOrderItem(draftFromService(cbc), "en")).toEqual({
      service_id: 3,
      quantity: 1,
      note: "",
      pre_approval_ref: "",
    });
    const drug = draftFromService(amoxicillin);
    const rx = drug.rx;
    if (!rx) throw new Error("a drug draft has a prescription");
    const item = toOrderItem({ ...drug, rx: { ...rx, frequencyCode: "TID", durationDays: "7" } }, "en");
    expect(item.quantity).toBeNull();
    expect(item.prescription).toMatchObject({
      dose: "1 capsule",
      dose_quantity: "1",
      frequency_code: "TID",
      duration_days: 7,
      route: "oral",
      as_needed: false,
    });
    expect(toOrderItem({ ...drug, quantity: "30" }, "ar").quantity).toBe(30);
    expect(toOrderItem(drug, "ar").prescription?.dose).toBe("1 كبسولة");
  });

  it("round-trips a favorite through an order set", () => {
    const drug = draftFromService(amoxicillin);
    const rx = drug.rx;
    if (!rx) throw new Error("a drug draft has a prescription");
    const items = [
      draftFromService(cbc),
      { ...drug, computedQuantity: 21, rx: { ...rx, frequencyCode: "TID", durationDays: "7" } },
    ];
    const favorite = toFavorite("Fever", items, "en");
    expect(favorite).toMatchObject({ name_ar: "", name_en: "Fever" });
    expect(favorite.items[1]).toMatchObject({
      service_id: 7,
      quantity: 21,
      dose_quantity: "1",
      route: "oral",
      frequency_code: "TID",
      duration_days: 7,
      as_needed: false,
    });
    expect(favorite.items[0]).toMatchObject({ dose_quantity: null, route: null, as_needed: false });

    const set: OrderSet = {
      id: 1,
      name_ar: "",
      name_en: "Fever",
      personal: true,
      department_id: null,
      items: [
        {
          service_id: 7,
          service_code: "DRG-AMOX500",
          kind: "drug",
          name_ar: "أموكسيسيلين 500",
          name_en: "Amoxicillin 500",
          quantity: "21",
          dose: "1 capsule",
          dose_quantity: "1",
          route: "oral",
          frequency_code: "TID",
          duration_days: 7,
          as_needed: false,
          instructions: "",
        },
      ],
    };
    const [loaded] = draftsFromOrderSet(set);
    // Countable again: the quantity follows dose x frequency x duration, not the saved number.
    expect(loaded?.quantity).toBe("");
    expect(loaded?.rx).toMatchObject({ frequencyCode: "TID", doseQuantity: "1", durationDays: "7" });
  });

  it("keeps an IV drug's route and an as-needed drug's quantity through a favorite", () => {
    if (!amoxicillin.drug) throw new Error("the fixture is a drug");
    const ceftriaxone: OrderableService = {
      ...amoxicillin,
      id: 9,
      code: "DRG-CEFTRI1G",
      name_ar: "سيفترياكسون 1 غ",
      name_en: "Ceftriaxone 1 g",
      drug: { ...amoxicillin.drug, base_unit_name_en: "vial", classes: [] },
    };
    const paracetamol: OrderableService = { ...ceftriaxone, id: 10, code: "DRG-PARA" };
    const iv = draftFromService(ceftriaxone);
    const prn = draftFromService(paracetamol);
    if (!iv.rx || !prn.rx) throw new Error("drug drafts have a prescription");
    const items = [
      { ...iv, computedQuantity: 10, rx: { ...iv.rx, route: "iv" as const, frequencyCode: "Q12H", durationDays: "5" } },
      { ...prn, quantity: "10", rx: { ...prn.rx, asNeeded: true, frequencyCode: "Q6H" } },
    ];
    const favorite = toFavorite("Pneumonia", items, "en");
    const saved: OrderSet = {
      id: 2,
      name_ar: "",
      name_en: "Pneumonia",
      personal: true,
      department_id: null,
      items: favorite.items.map((it, i) => ({
        service_id: it.service_id,
        service_code: i === 0 ? "DRG-CEFTRI1G" : "DRG-PARA",
        kind: "drug",
        name_ar: "",
        name_en: "",
        quantity: String(it.quantity),
        dose: it.dose,
        dose_quantity: it.dose_quantity == null ? null : String(it.dose_quantity),
        route: it.route ?? null,
        frequency_code: it.frequency_code,
        duration_days: it.duration_days ?? null,
        as_needed: it.as_needed,
        instructions: it.instructions,
      })),
    };
    const [ivBack, prnBack] = draftsFromOrderSet(saved);
    expect(ivBack?.rx).toMatchObject({ route: "iv", doseQuantity: "1", frequencyCode: "Q12H", durationDays: "5" });
    expect(ivBack?.quantity).toBe("");
    if (!ivBack) throw new Error("the IV drug comes back");
    expect(toOrderItem(ivBack, "en").prescription?.route).toBe("iv");
    expect(prnBack?.rx?.asNeeded).toBe(true);
    expect(prnBack?.quantity).toBe("10");
  });
});

describe("clinic display helpers", () => {
  const patient: PatientBrief = {
    id: 1,
    file_no: "PT-2026-000001",
    full_name_ar: "خالد عثمان",
    full_name_en: "Khalid Osman",
    sex: "male",
    date_of_birth: "1990-01-01",
    dob_is_estimated: false,
    phone: "",
    is_incomplete: false,
  };

  it("tells never-recorded allergies from none known", () => {
    expect(toPatientCard(patient, [], false, null, "en").allergies).toBeNull();
    expect(toPatientCard(patient, [], true, null, "en").allergies).toEqual([]);
    const chips = [{ id: 1, label_ar: "البنسلينات", label_en: "Penicillins", severity: "severe" as const }];
    expect(toPatientCard(patient, chips, true, null, "ar").allergies).toEqual(["البنسلينات"]);
  });

  it("maps doctor statuses onto the shared line badges", () => {
    expect(lineBadgeState("requested")).toBe("requested");
    expect(lineBadgeState("in_progress")).toBe("paid");
    expect(lineBadgeState("done")).toBe("performed");
  });

  it("reads the allergy matches of a 409 ALLERGY_CONFLICT only", () => {
    const alert = {
      service_id: 7,
      allergy_id: 2,
      match: "drug_class",
      severity: "severe",
      allergen: "Penicillins",
      allergen_ar: "البنسلينات",
    };
    const conflict = new ApiError(409, { code: "ALLERGY_CONFLICT", message: "", details: { alerts: [alert, "junk"] } });
    expect(allergyConflict(conflict)).toEqual([alert]);
    expect(allergyConflict(new ApiError(409, { code: "VISIT_NOT_OPEN", message: "", details: {} }))).toBeNull();
    expect(allergyConflict(new Error("x"))).toBeNull();
  });
});
