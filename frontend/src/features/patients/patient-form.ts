/** Registration and edit form: schema, defaults and conversion to the API bodies. */
import { z } from "zod";

import { vmsg } from "@/lib/validation";

import type { PatientFile, PatientInput, PatientPatch } from "./types";

const optionalPhone = z
  .string()
  .trim()
  .refine((v) => v === "" || /^0\d{9}$/.test(v), vmsg("validation.phone"));

/** Registration and edit form values (strings as typed; converted by toPatientInput). */
export const patientFormSchema = z
  .object({
    full_name_ar: z.string().trim().max(200),
    full_name_en: z.string().trim().max(200),
    // Starts empty: the clerk must choose (a preselected sex would register silently wrong).
    sex: z
      .enum(["male", "female", "unknown", ""], { message: vmsg("validation.selectOption") })
      .refine((v) => v.length > 0, vmsg("validation.selectOption")),
    dob_mode: z.enum(["date", "age"]),
    date_of_birth: z.string(),
    age_years: z.string().trim(),
    phone: optionalPhone,
    phone_alt: optionalPhone,
    national_id: z.string().trim().max(50),
    address: z.string().trim().max(300),
    emergency_contact_name: z.string().trim().max(150),
    emergency_contact_phone: optionalPhone,
    notes: z.string().trim().max(2000),
  })
  .refine((v) => v.full_name_ar !== "" || v.full_name_en !== "", {
    message: vmsg("patients:form.nameRequired"),
    path: ["full_name_ar"],
  })
  .refine((v) => v.dob_mode !== "age" || v.age_years === "" || /^\d{1,3}$/.test(v.age_years), {
    message: vmsg("validation.number"),
    path: ["age_years"],
  });

export type PatientFormValues = z.infer<typeof patientFormSchema>;

export const emptyPatientForm: PatientFormValues = {
  full_name_ar: "",
  full_name_en: "",
  sex: "",
  dob_mode: "date",
  date_of_birth: "",
  age_years: "",
  phone: "",
  phone_alt: "",
  national_id: "",
  address: "",
  emergency_contact_name: "",
  emergency_contact_phone: "",
  notes: "",
};

export function patientFormFrom(file: PatientFile): PatientFormValues {
  return {
    full_name_ar: file.full_name_ar,
    full_name_en: file.full_name_en,
    sex: file.sex,
    dob_mode: "date",
    date_of_birth: file.date_of_birth ?? "",
    age_years: "",
    phone: file.phone,
    phone_alt: file.phone_alt,
    national_id: file.national_id,
    address: file.address,
    emergency_contact_name: file.emergency_contact_name,
    emergency_contact_phone: file.emergency_contact_phone,
    notes: file.notes,
  };
}

function birth(values: PatientFormValues): Pick<PatientInput, "date_of_birth" | "age_years"> {
  if (values.dob_mode === "age") {
    return { date_of_birth: null, age_years: values.age_years === "" ? null : Number(values.age_years) };
  }
  return { date_of_birth: values.date_of_birth || null, age_years: null };
}

/**
 * Registration body. The chosen sex is sent as it is: the server accepts male or female only
 * ("unknown" is for emergency files) and answers anything else with a validation error.
 */
export function toPatientInput(values: PatientFormValues, confirmNotDuplicate = false): PatientInput {
  return {
    full_name_ar: values.full_name_ar,
    full_name_en: values.full_name_en,
    sex: values.sex as PatientInput["sex"],
    ...birth(values),
    phone: values.phone,
    phone_alt: values.phone_alt,
    national_id: values.national_id,
    address: values.address,
    emergency_contact_name: values.emergency_contact_name,
    emergency_contact_phone: values.emergency_contact_phone,
    notes: values.notes,
    confirm_not_duplicate: confirmNotDuplicate,
  };
}

/** Edit body: every field, birth from the date or the age the patient gave. */
export function toPatientPatch(values: PatientFormValues): PatientPatch {
  const patch: PatientPatch = {
    full_name_ar: values.full_name_ar,
    full_name_en: values.full_name_en,
    sex: values.sex as NonNullable<PatientPatch["sex"]>,
    phone: values.phone,
    phone_alt: values.phone_alt,
    national_id: values.national_id,
    address: values.address,
    emergency_contact_name: values.emergency_contact_name,
    emergency_contact_phone: values.emergency_contact_phone,
    notes: values.notes,
  };
  const { date_of_birth, age_years } = birth(values);
  if (age_years != null) patch.age_years = age_years;
  else if (date_of_birth) patch.date_of_birth = date_of_birth;
  return patch;
}
