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
    expect(favorite.items[1]).toMatchObject({ service_id: 7, quantity: 21, frequency_code: "TID", duration_days: 7 });

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
          frequency_code: "TID",
          duration_days: 7,
          instructions: "",
        },
      ],
    };
    const [loaded] = draftsFromOrderSet(set);
    expect(loaded?.quantity).toBe("21");
    expect(loaded?.rx?.frequencyCode).toBe("TID");
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
