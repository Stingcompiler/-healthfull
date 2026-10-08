import { describe, expect, it } from "vitest";

import {
  emptyPatientForm,
  patientFormFrom,
  patientFormSchema,
  toPatientInput,
  toPatientPatch,
  type PatientFormValues,
} from "./patient-form";
import type { PatientFile } from "./types";

const filled = (over: Partial<PatientFormValues> = {}): PatientFormValues => ({
  ...emptyPatientForm,
  full_name_ar: "عائشة محمد",
  sex: "female",
  date_of_birth: "1988-03-14",
  phone: "0912345678",
  ...over,
});

const errorPaths = (values: PatientFormValues): string[] => {
  const result = patientFormSchema.safeParse(values);
  return result.success ? [] : result.error.issues.map((i) => i.path.join("."));
};

describe("patient form", () => {
  it("starts with no sex chosen and requires a choice", () => {
    expect(emptyPatientForm.sex).toBe("");
    expect(errorPaths(filled({ sex: "" }))).toContain("sex");
    expect(errorPaths(filled())).toEqual([]);
  });

  it("needs a name in one script and valid phones and ages", () => {
    expect(errorPaths(filled({ full_name_ar: " " }))).toContain("full_name_ar");
    expect(errorPaths(filled({ full_name_ar: "", full_name_en: "Aisha" }))).toEqual([]);
    expect(errorPaths(filled({ phone: "12345" }))).toContain("phone");
    expect(errorPaths(filled({ dob_mode: "age", age_years: "4a" }))).toContain("age_years");
  });

  it("sends the chosen sex as it is (the server decides what registration accepts)", () => {
    expect(toPatientInput(filled({ sex: "female" })).sex).toBe("female");
    expect(toPatientInput(filled({ sex: "male" })).sex).toBe("male");
    expect(toPatientInput(filled({ sex: "unknown" })).sex).toBe("unknown");
  });

  it("converts the birth to a date or an age, never both", () => {
    const byDate = toPatientInput(filled());
    expect([byDate.date_of_birth, byDate.age_years]).toEqual(["1988-03-14", null]);
    const byAge = toPatientInput(filled({ dob_mode: "age", age_years: "42", date_of_birth: "1988-03-14" }));
    expect([byAge.date_of_birth, byAge.age_years]).toEqual([null, 42]);
    const none = toPatientInput(filled({ date_of_birth: "" }));
    expect([none.date_of_birth, none.age_years]).toEqual([null, null]);
    expect(toPatientInput(filled(), true).confirm_not_duplicate).toBe(true);
    expect(toPatientInput(filled()).confirm_not_duplicate).toBe(false);
  });

  it("patches every field and only the birth value given", () => {
    const byAge = toPatientPatch(filled({ dob_mode: "age", age_years: "30" }));
    expect(byAge.age_years).toBe(30);
    expect(byAge).not.toHaveProperty("date_of_birth");
    const byDate = toPatientPatch(filled());
    expect(byDate.date_of_birth).toBe("1988-03-14");
    expect(byDate).not.toHaveProperty("age_years");
    const blank = toPatientPatch(filled({ date_of_birth: "" }));
    expect(blank).not.toHaveProperty("date_of_birth");
    expect(blank).not.toHaveProperty("age_years");
    expect(byDate.sex).toBe("female");
    expect(byDate.full_name_ar).toBe("عائشة محمد");
  });

  it("reads a file back into the form (an emergency file keeps sex unknown)", () => {
    const file = {
      full_name_ar: "مجهول",
      full_name_en: "",
      sex: "unknown",
      date_of_birth: null,
      phone: "",
      phone_alt: "",
      national_id: "",
      address: "",
      emergency_contact_name: "",
      emergency_contact_phone: "",
      notes: "",
    } as unknown as PatientFile;
    const values = patientFormFrom(file);
    expect(values.sex).toBe("unknown");
    expect(values.date_of_birth).toBe("");
    expect(toPatientPatch(values).sex).toBe("unknown");
  });
});
