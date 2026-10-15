import type { PatientCardPatient } from "@/components/PatientCard";
import type { ServiceLineState } from "@/components/status";
import type { BilingualName } from "@/lib/names";

/*
 * DEV ONLY (phase 1 of the UI review): realistic content for the direction exploration at
 * /design/directions. Amounts are decimal strings as the API sends them; the payer/patient split
 * follows the AMAN seed rules (price list = cash x 0.90, payer pays 70%, patient the rest).
 */

export interface DirKpiData {
  collected: string;
  cash: string;
  bank: string;
  pending: string;
  pendingCount: number;
  queueWaiting: number;
  withDoctor: number;
  netRevenue: string;
  visits: number;
}

export const KPI: DirKpiData = {
  collected: "4862500.00",
  cash: "3240000.00",
  bank: "1622500.00",
  pending: "785000.00",
  pendingCount: 4,
  queueWaiting: 12,
  withDoctor: 5,
  netRevenue: "5310250.50",
  visits: 87,
};

export interface DirAlert {
  key: "stale_transfers" | "unreviewed_variances" | "expiring_stock" | "paid_not_performed";
  tone: "warning" | "danger" | "info";
  count: number;
  amount: string | null;
}

export const ALERTS: readonly DirAlert[] = [
  { key: "unreviewed_variances", tone: "danger", count: 2, amount: "18500.00" },
  { key: "stale_transfers", tone: "warning", count: 3, amount: "410000.00" },
  { key: "expiring_stock", tone: "warning", count: 6, amount: null },
  { key: "paid_not_performed", tone: "info", count: 1, amount: "13500.00" },
];

export const PATIENT: PatientCardPatient = {
  nameAr: "فاطمة عثمان محمد الحسن الطيب",
  nameEn: "Fatima Osman Mohamed Alhassan Altayeb",
  fileNo: "PT-2026-000075",
  sex: "female",
  birthDate: "1988-03-14",
  phone: "0912345678",
  allergies: ["البنسلين", "الأسبرين"],
  coverage: { nameAr: "شركة شيكان للتأمين الصحي", nameEn: "Shiekan Health Insurance", cardNo: "SH-55120" },
};

export interface DirLine {
  id: number;
  service: BilingualName;
  code: string;
  payer: BilingualName | null;
  quantity: number;
  unitPrice: string;
  gross: string;
  discount: string;
  payerShare: string;
  patientShare: string;
  state: ServiceLineState;
  /** "excluded" = not covered, "preapproval" = needs a pre-approval reference. */
  flag?: "excluded" | "preapproval";
}

const SHIEKAN: BilingualName = { ar: "شركة شيكان للتأمين الصحي", en: "Shiekan Health Insurance" };

export const LINES: readonly DirLine[] = [
  {
    id: 1,
    service: { ar: "كشف باطنية — استشاري", en: "Internal medicine consultation" },
    code: "CONS-GEN",
    payer: SHIEKAN,
    quantity: 1,
    unitPrice: "13500.00",
    gross: "13500.00",
    discount: "0.00",
    payerShare: "9450.00",
    patientShare: "4050.00",
    state: "paid",
  },
  {
    id: 2,
    service: { ar: "صورة دم كاملة (CBC)", en: "Complete blood count (CBC)" },
    code: "LAB-CBC",
    payer: SHIEKAN,
    quantity: 1,
    unitPrice: "10800.00",
    gross: "10800.00",
    discount: "0.00",
    payerShare: "7560.00",
    patientShare: "3240.00",
    state: "invoiced",
  },
  {
    id: 3,
    service: { ar: "أموكسيسيلين 500 مجم كبسولات", en: "Amoxicillin 500 mg capsules" },
    code: "DRG-AMOX500",
    payer: SHIEKAN,
    quantity: 15,
    unitPrice: "270.00",
    gross: "4050.00",
    discount: "0.00",
    payerShare: "2835.00",
    patientShare: "1215.00",
    state: "performed",
  },
  {
    id: 4,
    service: { ar: "سونار حوض وبطن بالموجات فوق الصوتية", en: "Pelvic and abdominal ultrasound" },
    code: "GYN-US",
    payer: SHIEKAN,
    quantity: 1,
    unitPrice: "18000.00",
    gross: "18000.00",
    discount: "0.00",
    payerShare: "12600.00",
    patientShare: "5400.00",
    state: "invoiced",
    flag: "preapproval",
  },
  {
    id: 5,
    service: { ar: "حشو أسنان تجميلي", en: "Cosmetic dental filling" },
    code: "DEN-FILL",
    payer: null,
    quantity: 1,
    unitPrice: "30000.00",
    gross: "30000.00",
    discount: "3000.00",
    payerShare: "0.00",
    patientShare: "27000.00",
    state: "invoiced",
    flag: "excluded",
  },
  {
    id: 6,
    service: { ar: "غيار جرح", en: "Wound dressing" },
    code: "PRC-DRESS",
    payer: null,
    quantity: 1,
    unitPrice: "5000.00",
    gross: "5000.00",
    discount: "0.00",
    payerShare: "0.00",
    patientShare: "5000.00",
    state: "cancelled",
  },
];

export const TOTALS = {
  gross: "76350.00",
  discount: "3000.00",
  payerShare: "32445.00",
  patientShare: "40905.00",
};
