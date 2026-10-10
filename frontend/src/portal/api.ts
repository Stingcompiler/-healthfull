/**
 * TanStack Query hooks of the patient portal. The portal session is its own HttpOnly cookie
 * (path /api/portal); every rule is the server's. Queries carry `meta.portal` so the signed-in
 * layout can send the patient back to sign-in when the session ends (401).
 */
import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { ensureCsrfToken } from "@/lib/api/csrf";

import type { PortalLoginIn, PortalMe } from "./types";

export const portalKeys = {
  all: ["portal"] as const,
  me: ["portal", "me"] as const,
  summary: ["portal", "summary"] as const,
  appointments: ["portal", "appointments"] as const,
  doctors: ["portal", "doctors"] as const,
  days: (doctorId: number) => ["portal", "days", doctorId] as const,
  slots: (doctorId: number, on: string) => ["portal", "slots", doctorId, on] as const,
  results: ["portal", "results"] as const,
  result: (lineId: number) => ["portal", "result", lineId] as const,
  prescriptions: ["portal", "prescriptions"] as const,
  invoices: ["portal", "invoices"] as const,
  invoice: (id: number) => ["portal", "invoice", id] as const,
  receipts: ["portal", "receipts"] as const,
  receipt: (id: number) => ["portal", "receipt", id] as const,
  balance: ["portal", "balance"] as const,
  verify: (receipt: string, token: string) => ["portal-verify", receipt, token] as const,
};

const PORTAL_META = { portal: true } as const;

/** The signed-in patient, or null. Asks the always-200 session probe, so a signed-out
 * visitor causes no failed request. */
export async function fetchPortalMe(): Promise<PortalMe | null> {
  const session = await unwrap(api.GET("/api/portal/session"));
  return session.me ?? null;
}

export const portalMeQuery = queryOptions({
  queryKey: portalKeys.me,
  queryFn: fetchPortalMe,
  staleTime: 60_000,
  retry: false,
});

export function usePortalMe() {
  return useQuery(portalMeQuery);
}

export async function portalLogin(body: PortalLoginIn): Promise<PortalMe> {
  await ensureCsrfToken();
  return unwrap(api.POST("/api/portal/session", { body }));
}

export async function portalLogout(): Promise<void> {
  await unwrap(api.POST("/api/portal/session/logout"));
}

export function useSummary() {
  return useQuery({
    queryKey: portalKeys.summary,
    queryFn: () => unwrap(api.GET("/api/portal/summary")),
    meta: PORTAL_META,
  });
}

export function useAppointments() {
  return useQuery({
    queryKey: portalKeys.appointments,
    queryFn: () => unwrap(api.GET("/api/portal/appointments")),
    meta: PORTAL_META,
  });
}

export function useDoctors() {
  return useQuery({
    queryKey: portalKeys.doctors,
    queryFn: () => unwrap(api.GET("/api/portal/doctors")),
    meta: PORTAL_META,
  });
}

export function useBookingDays(doctorId: number | null) {
  return useQuery({
    queryKey: portalKeys.days(doctorId ?? 0),
    queryFn: () =>
      unwrap(api.GET("/api/portal/doctors/{doctor_id}/days", { params: { path: { doctor_id: doctorId ?? 0 } } })),
    enabled: doctorId !== null,
    meta: PORTAL_META,
  });
}

export function useSlots(doctorId: number | null, on: string | null) {
  return useQuery({
    queryKey: portalKeys.slots(doctorId ?? 0, on ?? ""),
    queryFn: () =>
      unwrap(
        api.GET("/api/portal/doctors/{doctor_id}/slots", {
          params: { path: { doctor_id: doctorId ?? 0 }, query: { on: on ?? "" } },
        }),
      ),
    enabled: doctorId !== null && on !== null,
    staleTime: 0,
    meta: PORTAL_META,
  });
}

export function useBookAppointment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { doctor_id: number; starts_at: string }) =>
      unwrap(api.POST("/api/portal/appointments", { body })),
    meta: PORTAL_META,
    onSettled: () => queryClient.invalidateQueries({ queryKey: portalKeys.all }),
  });
}

export function useCancelAppointment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (appointmentId: number) =>
      unwrap(
        api.POST("/api/portal/appointments/{appointment_id}/cancel", {
          params: { path: { appointment_id: appointmentId } },
        }),
      ),
    meta: PORTAL_META,
    onSettled: () => queryClient.invalidateQueries({ queryKey: portalKeys.all }),
  });
}

export function useResults() {
  return useQuery({
    queryKey: portalKeys.results,
    queryFn: () => unwrap(api.GET("/api/portal/results")),
    meta: PORTAL_META,
  });
}

export function useResult(lineId: number) {
  return useQuery({
    queryKey: portalKeys.result(lineId),
    queryFn: () => unwrap(api.GET("/api/portal/results/{line_id}", { params: { path: { line_id: lineId } } })),
    meta: PORTAL_META,
  });
}

export function usePrescriptions() {
  return useQuery({
    queryKey: portalKeys.prescriptions,
    queryFn: () => unwrap(api.GET("/api/portal/prescriptions")),
    meta: PORTAL_META,
  });
}

export function useInvoices() {
  return useQuery({
    queryKey: portalKeys.invoices,
    queryFn: () => unwrap(api.GET("/api/portal/invoices")),
    meta: PORTAL_META,
  });
}

export function useInvoice(invoiceId: number) {
  return useQuery({
    queryKey: portalKeys.invoice(invoiceId),
    queryFn: () =>
      unwrap(api.GET("/api/portal/invoices/{invoice_id}", { params: { path: { invoice_id: invoiceId } } })),
    meta: PORTAL_META,
  });
}

export function useReceipts() {
  return useQuery({
    queryKey: portalKeys.receipts,
    queryFn: () => unwrap(api.GET("/api/portal/receipts")),
    meta: PORTAL_META,
  });
}

export function useReceipt(paymentId: number) {
  return useQuery({
    queryKey: portalKeys.receipt(paymentId),
    queryFn: () =>
      unwrap(api.GET("/api/portal/receipts/{payment_id}", { params: { path: { payment_id: paymentId } } })),
    meta: PORTAL_META,
  });
}

export function useBalance() {
  return useQuery({
    queryKey: portalKeys.balance,
    queryFn: () => unwrap(api.GET("/api/portal/balance")),
    meta: PORTAL_META,
  });
}

/** Public receipt check (no session). */
export function useVerifyReceipt(receipt: string | null, token: string) {
  return useQuery({
    queryKey: portalKeys.verify(receipt ?? "", token),
    queryFn: () => unwrap(api.GET("/api/portal/verify", { params: { query: { receipt: receipt ?? "", token } } })),
    enabled: Boolean(receipt) && Boolean(token),
    retry: false,
    staleTime: 5 * 60_000,
  });
}

/** Staff: a new portal access code for the patient of a receipt (shown once). */
export function useIssuePortalCode() {
  return useMutation({
    mutationFn: (paymentId: number) =>
      unwrap(api.POST("/api/portal/access-codes", { body: { payment_id: paymentId } })),
  });
}
