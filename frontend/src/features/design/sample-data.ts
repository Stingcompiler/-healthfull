import type { PatientCardPatient } from "@/components/PatientCard";
import type { Status } from "@/components/status";
import type { BilingualName } from "@/lib/names";

/*
 * Synthetic data for the style guide only. Names are fictional; amounts are
 * decimal strings exactly as the API sends them.
 */
export const SAMPLE_PATIENTS: readonly PatientCardPatient[] = [
  {
    nameAr: "فاطمة عثمان محمد الحسن",
    nameEn: "Fatima Osman Mohamed Alhassan",
    fileNo: "2026-00412",
    sex: "female",
    birthDate: "1988-03-14",
    phone: "0912345678",
    allergies: ["البنسلين", "الأسبرين"],
    coverage: { nameAr: "شركة شيكان للتأمين", nameEn: "Shiekan Insurance", cardNo: "SH-55120" },
  },
  {
    nameAr: "أحمد عبد الرحيم يوسف",
    nameEn: "Ahmed Abdelrahim Yousif",
    fileNo: "2026-00413",
    sex: "male",
    ageYears: 54,
    phone: "0123456789",
    allergies: [],
    coverage: null,
  },
  {
    nameAr: "مولود — طوارئ",
    nameEn: null,
    fileNo: "2026-00414",
    sex: "male",
    birthDate: "2026-07-20",
    allergies: null,
    coverage: null,
    incomplete: true,
  },
];

export interface SampleLine {
  id: string;
  fileNo: string;
  patient: BilingualName;
  service: BilingualName;
  amount: string;
  status: Status;
  date: string;
}

const PEOPLE: BilingualName[] = [
  { ar: "فاطمة عثمان", en: "Fatima Osman" },
  { ar: "أحمد عبد الرحيم", en: "Ahmed Abdelrahim" },
  { ar: "مريم الطيب", en: "Mariam Altayeb" },
  { ar: "عمر حسن البشير", en: "Omar Hassan Albashir" },
  { ar: "سارة إبراهيم", en: "Sara Ibrahim" },
  { ar: "خالد محجوب", en: "Khalid Mahgoub" },
];

const SERVICES: { name: BilingualName; amount: string }[] = [
  { name: { ar: "كشف باطنية", en: "Internal medicine consultation" }, amount: "15000.00" },
  { name: { ar: "صورة دم كاملة", en: "Complete blood count" }, amount: "8500.00" },
  { name: { ar: "سكر صائم", en: "Fasting blood sugar" }, amount: "3000.00" },
  { name: { ar: "أموكسيسيلين 500 مجم × 15", en: "Amoxicillin 500 mg × 15" }, amount: "4750.50" },
  { name: { ar: "غيار جرح", en: "Wound dressing" }, amount: "6000.00" },
  { name: { ar: "تخطيط قلب", en: "Electrocardiogram" }, amount: "12000.00" },
];

const STATES: Status[] = [
  "requested",
  "invoiced",
  "paid",
  "performed",
  "cancelled",
  "pending_verification",
  "confirmed",
  "rejected",
];

export const SAMPLE_LINES: readonly SampleLine[] = Array.from({ length: 14 }, (_, i) => {
  const person = PEOPLE[i % PEOPLE.length] ?? { ar: "", en: "" };
  const service = SERVICES[(i * 5) % SERVICES.length] ?? { name: { ar: "", en: "" }, amount: "0.00" };
  const day = String(1 + (i % 6)).padStart(2, "0");
  const hour = String(8 + (i % 9)).padStart(2, "0");
  return {
    id: `SL-${String(1040 + i)}`,
    fileNo: `2026-${String(412 + (i % PEOPLE.length)).padStart(5, "0")}`,
    patient: person,
    service: service.name,
    amount: service.amount,
    status: STATES[i % STATES.length] ?? "requested",
    date: `2026-10-${day}T${hour}:15:00+02:00`,
  };
});

/** Service and staff names used by the card examples. */
export const SAMPLE_NAMES = {
  consult: { ar: "كشف باطنية", en: "Internal medicine consultation" },
  cbc: { ar: "صورة دم كاملة", en: "Complete blood count" },
  amox: { ar: "أموكسيسيلين 500 مجم", en: "Amoxicillin 500 mg" },
  dressing: { ar: "غيار جرح", en: "Wound dressing" },
  ecg: { ar: "تخطيط قلب", en: "Electrocardiogram" },
  doctor: { ar: "د. عبد الله النور", en: "Dr. Abdalla Alnour" },
} as const satisfies Record<string, BilingualName>;
