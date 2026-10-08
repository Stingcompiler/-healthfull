/** Named aliases of the cashier API schemas (generated from openapi.json, never hand-written). */
import type { components } from "@/lib/api/schema";

type S = components["schemas"];

export type NameRef = S["NameOut"];
export type UserRef = S["UserRefOut"];
export type Reason = S["ReasonOut"];
export type PatientSummary = S["PatientSummaryOut"];
export type Balance = S["BalanceOut"];
export type LookupResult = S["LookupOut"];
export type LookupPatient = S["LookupPatientOut"];
export type LookupVisit = S["LookupVisitOut"];
export type VisitBilling = S["VisitBillingOut"];
export type ServiceLine = S["ServiceLineOut"];
export type Invoice = S["InvoiceOut"];
export type InvoiceLine = S["InvoiceLineOut"];
export type InvoicePrint = S["InvoicePrintOut"];
export type CreditNote = S["CreditNoteOut"];
export type CreditOutcome = S["CreditOutcomeOut"];
export type DiscountIn = S["DiscountIn"];
export type CreditNoteIn = S["CreditNoteIn"];
export type CreditNoteApproveIn = S["CreditNoteApproveIn"];
export type ShiftReport = S["ShiftReportOut"];
export type Shift = S["ShiftOut"];
export type CurrentShift = S["CurrentShiftOut"];
export type ShiftListItem = S["ShiftListItemOut"];
export type ShiftOpenIn = S["ShiftOpenIn"];
export type ShiftCloseIn = S["ShiftCloseIn"];
export type ShiftReviewIn = S["ShiftReviewIn"];
export type Handover = S["HandoverOut"];
export type HandoverIn = S["HandoverIn"];
export type OpenShiftRef = S["OpenShiftRefOut"];
export type PaymentIn = S["PaymentIn"];
export type Payment = S["PaymentOut"];
export type Receipt = S["ReceiptOut"];
export type Transfer = S["TransferOut"];
export type Rejection = S["RejectionOut"];
export type Refund = S["RefundOut"];
export type RefundIn = S["RefundIn"];
export type PerformFirstVisit = S["PerformFirstVisitOut"];
export type AuthorizableLine = S["AuthorizableLineOut"];
export type Authorization = S["AuthorizationOut"];
export type AuthorizeIn = S["AuthorizeIn"];
export type Center = S["CenterOut"];

export type PaymentMethod = PaymentIn["method"];
export type ReasonCategory =
  "discount" | "credit_note" | "line_cancel" | "override" | "variance" | "refund" | "transfer_reject" | "perform_first";
export type Verification = Payment["verification"];
export type RefundStatus = Refund["status"];
export type DocStatus = Invoice["status"];

export const PAYMENT_METHODS: readonly PaymentMethod[] = ["cash", "bank_transfer", "qr", "card", "patient_credit"];
/** Methods that carry a bank and a reference and start pending (ARCHITECTURE 4.6). */
export const REFERENCE_METHODS: readonly PaymentMethod[] = ["bank_transfer", "qr", "card"];
