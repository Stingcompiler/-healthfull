/**
 * createPatient through /api/patients (registration and emergency registration). Options the
 * endpoints do not cover in one call (a payer on file, allergies) go back to the fixture.
 */
import { registerAdapter, type PatientRef } from "../api";

const FIRST = ["أحمد", "محمد", "عثمان", "فاطمة", "آمنة", "مريم", "خالد", "سلمى", "يوسف", "هالة"];
const FATHER = ["عبدالله", "الطيب", "إبراهيم", "الأمين", "حسن", "بشير", "النور", "عوض"];

function pick<T>(items: readonly T[]): T {
  return items[Math.floor(Math.random() * items.length)] as T;
}

function randomPhone(): string {
  return `09${String(Math.floor(Math.random() * 1e8)).padStart(8, "0")}`;
}

registerAdapter("createPatient", {
  operations: ["patients_create_patient", "patients_register_emergency"],
  async run(options, api) {
    if (options.payer !== undefined || options.allergies?.length) return undefined;
    const reception = await api(options.as ?? "reception");
    if (options.emergency) {
      const patient = await reception.call<PatientRef>("patients_register_emergency", {
        body: {
          name: options.full_name_ar ?? options.full_name_en ?? `${pick(FIRST)} ${pick(FATHER)}`,
          sex: options.sex ?? "unknown",
          age_years: options.age_years ?? null,
          phone: options.phone ?? "",
        },
      });
      return { patient, coverage: null, allergies: [] };
    }
    const named = options.full_name_ar !== undefined || options.full_name_en !== undefined;
    const patient = await reception.call<PatientRef>("patients_create_patient", {
      body: {
        full_name_ar: named ? (options.full_name_ar ?? "") : `${pick(FIRST)} ${pick(FATHER)} ${pick(FATHER)}`,
        full_name_en: options.full_name_en ?? "",
        // As given: the server refuses "unknown" outside emergency registration.
        sex: options.sex ?? "male",
        date_of_birth: options.date_of_birth ?? (options.age_years === undefined ? "1990-01-15" : null),
        age_years: options.age_years ?? null,
        phone: options.phone ?? randomPhone(),
        phone_alt: options.phone_alt ?? "",
        address: options.address ?? "",
        national_id: options.national_id ?? "",
        emergency_contact_name: options.emergency_contact_name ?? "",
        emergency_contact_phone: options.emergency_contact_phone ?? "",
        notes: options.notes ?? "",
        confirm_not_duplicate: options.confirm_not_duplicate ?? true,
      },
    });
    return { patient, coverage: null, allergies: [] };
  },
});
