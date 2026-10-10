/** Portal API shapes, aliased from the generated contract (`make api`). Nothing hand-written. */
import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];

export type PortalMe = Schemas["PortalMeOut"];
export type PortalLoginIn = Schemas["PortalLoginIn"];
export type PortalSummary = Schemas["PortalSummaryOut"];
export type PortalAppointment = Schemas["PortalAppointmentOut"];
export type PortalAppointments = Schemas["PortalAppointmentsOut"];
export type PortalDoctor = Schemas["PortalDoctorOut"];
export type PortalSlots = Schemas["PortalSlotsOut"];
export type PortalResultSummary = Schemas["PortalResultSummaryOut"];
export type PortalResult = Schemas["PortalResultOut"];
export type PortalResultValue = Schemas["PortalResultValueOut"];
export type PortalPrescriptions = Schemas["PortalPrescriptionsOut"];
export type PortalPrescriptionItem = Schemas["PortalPrescriptionItemOut"];
export type PortalInvoice = Schemas["PortalInvoiceOut"];
export type PortalInvoiceDetail = Schemas["PortalInvoiceDetailOut"];
export type PortalReceipt = Schemas["PortalReceiptOut"];
export type PortalReceiptDetail = Schemas["PortalReceiptDetailOut"];
export type PortalBalance = Schemas["PortalBalanceOut"];
export type PortalVerify = Schemas["PortalVerifyOut"];
export type PortalIssuedCode = Schemas["PortalIssuedCodeOut"];
export type PortalCenter = Schemas["PortalCenterOut"];
