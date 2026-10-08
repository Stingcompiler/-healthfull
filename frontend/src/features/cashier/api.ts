/**
 * TanStack Query hooks of the cashier module (ARCHITECTURE 5.5). Every rule is the server's:
 * these hooks only fetch, send and refresh what the screens show.
 */
import { keepPreviousData, queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";

import type {
  AuthorizeIn,
  CreditNoteApproveIn,
  CreditNoteIn,
  DiscountIn,
  DocStatus,
  HandoverIn,
  PaymentIn,
  ReasonCategory,
  RefundIn,
  RefundStatus,
  ShiftCloseIn,
  ShiftOpenIn,
  ShiftReviewIn,
  Verification,
} from "./types";

export const cashierKeys = {
  all: ["cashier"] as const,
  lookup: (q: string) => ["cashier", "lookup", q] as const,
  visit: (visitId: number) => ["cashier", "visit", visitId] as const,
  invoice: (invoiceId: number) => ["cashier", "invoice", invoiceId] as const,
  invoicePrint: (invoiceId: number) => ["cashier", "invoice-print", invoiceId] as const,
  reasons: (category: ReasonCategory) => ["cashier", "reasons", category] as const,
  banks: ["cashier", "banks"] as const,
  tills: ["cashier", "tills"] as const,
  currentShift: ["cashier", "shift", "current"] as const,
  shift: (shiftId: number) => ["cashier", "shift", shiftId] as const,
  shifts: (filters: { status?: string; reviewed?: boolean; page: number }) => ["cashier", "shifts", filters] as const,
  handoverTargets: ["cashier", "handover-targets"] as const,
  handoverReceivers: ["cashier", "handover-receivers"] as const,
  receiptCheck: (code: string) => ["cashier", "receipt-check", code] as const,
  payment: (paymentId: number) => ["cashier", "payment", paymentId] as const,
  receipt: (paymentId: number) => ["cashier", "receipt", paymentId] as const,
  transfers: (verification: Verification, page: number) => ["cashier", "transfers", verification, page] as const,
  creditNotes: (status: DocStatus | undefined, page: number) => ["cashier", "credit-notes", status, page] as const,
  refunds: (status: RefundStatus | undefined, page: number) => ["cashier", "refunds", status, page] as const,
  performFirstVisit: (visitId: number) => ["cashier", "perform-first", "visit", visitId] as const,
  authorizations: (active: boolean | undefined, page: number) =>
    ["cashier", "perform-first", "list", active, page] as const,
};

/** Page size of the cashier queues. */
export const PAGE_SIZE = 25;

// --- reads ------------------------------------------------------------------------------------

export function useLookup(q: string) {
  const term = q.trim();
  return useQuery({
    queryKey: cashierKeys.lookup(term),
    queryFn: () => unwrap(api.GET("/api/billing/lookup", { params: { query: { q: term } } })),
    enabled: term.length > 0,
    placeholderData: keepPreviousData,
    staleTime: 5_000,
  });
}

export function useVisitBilling(visitId: number | undefined) {
  return useQuery({
    queryKey: cashierKeys.visit(visitId ?? 0),
    queryFn: () => unwrap(api.GET("/api/billing/visits/{visit_id}", { params: { path: { visit_id: visitId ?? 0 } } })),
    enabled: visitId !== undefined,
    staleTime: 0,
  });
}

export function useInvoicePrint(invoiceId: number) {
  return useQuery({
    queryKey: cashierKeys.invoicePrint(invoiceId),
    queryFn: () =>
      unwrap(api.GET("/api/billing/invoices/{invoice_id}/print", { params: { path: { invoice_id: invoiceId } } })),
  });
}

export const reasonsQuery = (category: ReasonCategory) =>
  queryOptions({
    queryKey: cashierKeys.reasons(category),
    queryFn: () => unwrap(api.GET("/api/billing/reasons", { params: { query: { category } } })),
    staleTime: 5 * 60_000,
  });

export function useReasons(category: ReasonCategory, enabled = true) {
  return useQuery({ ...reasonsQuery(category), enabled });
}

export function useBanks(enabled = true) {
  return useQuery({
    queryKey: cashierKeys.banks,
    queryFn: () => unwrap(api.GET("/api/payments/banks")),
    staleTime: 5 * 60_000,
    enabled,
  });
}

export function useTills(enabled = true) {
  return useQuery({
    queryKey: cashierKeys.tills,
    queryFn: () => unwrap(api.GET("/api/payments/tills")),
    staleTime: 5 * 60_000,
    enabled,
  });
}

export function useCurrentShift(enabled = true) {
  return useQuery({
    queryKey: cashierKeys.currentShift,
    queryFn: () => unwrap(api.GET("/api/payments/shifts/current")),
    staleTime: 0,
    enabled,
  });
}

export function useShift(shiftId: number) {
  return useQuery({
    queryKey: cashierKeys.shift(shiftId),
    queryFn: () => unwrap(api.GET("/api/payments/shifts/{shift_id}", { params: { path: { shift_id: shiftId } } })),
  });
}

export function useShifts(filters: { status?: "open" | "closed"; reviewed?: boolean; page: number }) {
  return useQuery({
    queryKey: cashierKeys.shifts(filters),
    queryFn: () =>
      unwrap(
        api.GET("/api/payments/shifts", {
          params: {
            query: {
              status: filters.status ?? null,
              reviewed: filters.reviewed ?? null,
              page: filters.page,
              page_size: PAGE_SIZE,
            },
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

export function useHandoverTargets(enabled: boolean) {
  return useQuery({
    queryKey: cashierKeys.handoverTargets,
    queryFn: () => unwrap(api.GET("/api/payments/shifts/handover-targets")),
    enabled,
  });
}

export function useHandoverReceivers(enabled: boolean) {
  return useQuery({
    queryKey: cashierKeys.handoverReceivers,
    queryFn: () => unwrap(api.GET("/api/payments/handover-receivers")),
    enabled,
    staleTime: 60_000,
  });
}

/** Check a printed receipt by its scanned QR text or its number (FEATURES 6.9, 15.1). */
export function useReceiptCheck(code: string) {
  const term = code.trim();
  return useQuery({
    queryKey: cashierKeys.receiptCheck(term),
    queryFn: () => unwrap(api.GET("/api/payments/receipts/check", { params: { query: { code: term } } })),
    enabled: term.length > 0,
    retry: false,
    staleTime: 0,
  });
}

export function useReceipt(paymentId: number) {
  return useQuery({
    queryKey: cashierKeys.receipt(paymentId),
    queryFn: () =>
      unwrap(api.GET("/api/payments/payments/{payment_id}/receipt", { params: { path: { payment_id: paymentId } } })),
  });
}

export function useTransfers(verification: Verification, page: number) {
  return useQuery({
    queryKey: cashierKeys.transfers(verification, page),
    queryFn: () =>
      unwrap(
        api.GET("/api/payments/transfers", {
          params: { query: { verification, page, page_size: PAGE_SIZE } },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

export function useCreditNotes(status: DocStatus | undefined, page: number) {
  return useQuery({
    queryKey: cashierKeys.creditNotes(status, page),
    queryFn: () =>
      unwrap(
        api.GET("/api/billing/credit-notes", {
          params: { query: { status: status ?? null, page, page_size: PAGE_SIZE } },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

export function useRefunds(status: RefundStatus | undefined, page: number) {
  return useQuery({
    queryKey: cashierKeys.refunds(status, page),
    queryFn: () =>
      unwrap(
        api.GET("/api/payments/refunds", {
          params: { query: { status: status ?? null, page, page_size: PAGE_SIZE } },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

export function usePerformFirstVisit(visitId: number | undefined) {
  return useQuery({
    queryKey: cashierKeys.performFirstVisit(visitId ?? 0),
    queryFn: () =>
      unwrap(api.GET("/api/orders/perform-first/visits/{visit_id}", { params: { path: { visit_id: visitId ?? 0 } } })),
    enabled: visitId !== undefined,
    staleTime: 0,
  });
}

export function useAuthorizations(active: boolean | undefined, page: number) {
  return useQuery({
    queryKey: cashierKeys.authorizations(active, page),
    queryFn: () =>
      unwrap(
        api.GET("/api/orders/perform-first", {
          params: { query: { active: active ?? null, page, page_size: PAGE_SIZE } },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

// --- commands ---------------------------------------------------------------------------------

/** Every cashier mutation refreshes the module's cached reads (they are cheap and shared). */
function useCashierMutation<TArgs, TResult>(fn: (args: TArgs) => Promise<TResult>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: cashierKeys.all });
    },
  });
}

export function useOpenShift() {
  return useCashierMutation((body: ShiftOpenIn) => unwrap(api.POST("/api/payments/shifts", { body })));
}

export function useCloseShift() {
  return useCashierMutation(({ shiftId, body }: { shiftId: number; body: ShiftCloseIn }) =>
    unwrap(api.POST("/api/payments/shifts/{shift_id}/close", { params: { path: { shift_id: shiftId } }, body })),
  );
}

export function useReviewShift() {
  return useCashierMutation(({ shiftId, body }: { shiftId: number; body: ShiftReviewIn }) =>
    unwrap(api.POST("/api/payments/shifts/{shift_id}/review", { params: { path: { shift_id: shiftId } }, body })),
  );
}

export function useCreateHandover() {
  return useCashierMutation(({ shiftId, body }: { shiftId: number; body: HandoverIn }) =>
    unwrap(api.POST("/api/payments/shifts/{shift_id}/handovers", { params: { path: { shift_id: shiftId } }, body })),
  );
}

export function useReceiveHandover() {
  return useCashierMutation((handoverId: number) =>
    unwrap(
      api.POST("/api/payments/handovers/{handover_id}/receive", { params: { path: { handover_id: handoverId } } }),
    ),
  );
}

export function useCancelHandover() {
  return useCashierMutation(({ handoverId, note }: { handoverId: number; note: string }) =>
    unwrap(
      api.POST("/api/payments/handovers/{handover_id}/cancel", {
        params: { path: { handover_id: handoverId } },
        body: { note },
      }),
    ),
  );
}

export function useCreateInvoice() {
  return useCashierMutation((body: { visit_id: number; line_ids?: number[] | null }) =>
    unwrap(api.POST("/api/billing/invoices", { body })),
  );
}

export function useApproveInvoice() {
  return useCashierMutation((invoiceId: number) =>
    unwrap(api.POST("/api/billing/invoices/{invoice_id}/approve", { params: { path: { invoice_id: invoiceId } } })),
  );
}

export function useVoidInvoice() {
  return useCashierMutation(({ invoiceId, note }: { invoiceId: number; note: string }) =>
    unwrap(
      api.POST("/api/billing/invoices/{invoice_id}/void", {
        params: { path: { invoice_id: invoiceId } },
        body: { note },
      }),
    ),
  );
}

export function useRemoveDraftLine() {
  return useCashierMutation(({ invoiceId, lineId }: { invoiceId: number; lineId: number }) =>
    unwrap(
      api.DELETE("/api/billing/invoices/{invoice_id}/lines/{line_id}", {
        params: { path: { invoice_id: invoiceId, line_id: lineId } },
      }),
    ),
  );
}

export function useCancelDraftLine() {
  return useCashierMutation(
    ({ invoiceId, lineId, reason, note }: { invoiceId: number; lineId: number; reason: string; note: string }) =>
      unwrap(
        api.POST("/api/billing/invoices/{invoice_id}/lines/{line_id}/cancel", {
          params: { path: { invoice_id: invoiceId, line_id: lineId } },
          body: { reason, note },
        }),
      ),
  );
}

export function useSetPreapproval() {
  return useCashierMutation(
    ({ invoiceId, lineId, reference }: { invoiceId: number; lineId: number; reference: string }) =>
      unwrap(
        api.POST("/api/billing/invoices/{invoice_id}/lines/{line_id}/pre-approval", {
          params: { path: { invoice_id: invoiceId, line_id: lineId } },
          body: { reference },
        }),
      ),
  );
}

export function useDiscountLine() {
  return useCashierMutation(({ invoiceId, lineId, body }: { invoiceId: number; lineId: number; body: DiscountIn }) =>
    unwrap(
      api.POST("/api/billing/invoices/{invoice_id}/lines/{line_id}/discount", {
        params: { path: { invoice_id: invoiceId, line_id: lineId } },
        body,
      }),
    ),
  );
}

export function useDiscountInvoice() {
  return useCashierMutation(({ invoiceId, body }: { invoiceId: number; body: DiscountIn }) =>
    unwrap(
      api.POST("/api/billing/invoices/{invoice_id}/discount", {
        params: { path: { invoice_id: invoiceId } },
        body,
      }),
    ),
  );
}

export function useSetLinePayer() {
  return useCashierMutation(
    ({ serviceLineId, payerId, note }: { serviceLineId: number; payerId: number | null; note: string }) =>
      unwrap(
        api.POST("/api/billing/lines/{service_line_id}/payer", {
          params: { path: { service_line_id: serviceLineId } },
          body: { payer_id: payerId, note },
        }),
      ),
  );
}

export function useCreateCreditNote() {
  return useCashierMutation(({ invoiceId, body }: { invoiceId: number; body: CreditNoteIn }) =>
    unwrap(
      api.POST("/api/billing/invoices/{invoice_id}/credit-notes", {
        params: { path: { invoice_id: invoiceId } },
        body,
      }),
    ),
  );
}

export function useApproveCreditNote() {
  return useCashierMutation(({ creditNoteId, body }: { creditNoteId: number; body: CreditNoteApproveIn }) =>
    unwrap(
      api.POST("/api/billing/credit-notes/{credit_note_id}/approve", {
        params: { path: { credit_note_id: creditNoteId } },
        body,
      }),
    ),
  );
}

export function useRecordPayment() {
  return useCashierMutation((body: PaymentIn) => unwrap(api.POST("/api/payments/payments", { body })));
}

/** Spend a payment's unallocated remainder on open invoices (one visit's, or oldest first). */
export function useAllocatePayment() {
  return useCashierMutation(({ paymentId, visitId }: { paymentId: number; visitId: number | null }) =>
    unwrap(
      api.POST("/api/payments/payments/{payment_id}/allocate", {
        params: { path: { payment_id: paymentId } },
        body: { auto: true, visit_id: visitId },
      }),
    ),
  );
}

export function useConfirmTransfer() {
  return useCashierMutation(({ paymentId, note }: { paymentId: number; note: string }) =>
    unwrap(
      api.POST("/api/payments/payments/{payment_id}/confirm", {
        params: { path: { payment_id: paymentId } },
        body: { note },
      }),
    ),
  );
}

export function useRejectTransfer() {
  return useCashierMutation(({ paymentId, reason, note }: { paymentId: number; reason: string; note: string }) =>
    unwrap(
      api.POST("/api/payments/payments/{payment_id}/reject", {
        params: { path: { payment_id: paymentId } },
        body: { reason, note },
      }),
    ),
  );
}

export function useRequestRefund() {
  return useCashierMutation((body: RefundIn) => unwrap(api.POST("/api/payments/refunds", { body })));
}

export function useDecideRefund() {
  return useCashierMutation(
    ({ refundId, decision, note }: { refundId: number; decision: "approve" | "reject"; note: string }) =>
      decision === "approve"
        ? unwrap(
            api.POST("/api/payments/refunds/{refund_id}/approve", {
              params: { path: { refund_id: refundId } },
              body: { note },
            }),
          )
        : unwrap(
            api.POST("/api/payments/refunds/{refund_id}/reject", {
              params: { path: { refund_id: refundId } },
              body: { note },
            }),
          ),
  );
}

export function usePayRefund() {
  return useCashierMutation((refundId: number) =>
    unwrap(api.POST("/api/payments/refunds/{refund_id}/pay", { params: { path: { refund_id: refundId } } })),
  );
}

export function useAuthorize() {
  return useCashierMutation((body: AuthorizeIn) => unwrap(api.POST("/api/orders/perform-first", { body })));
}

export function useRevokeAuthorization() {
  return useCashierMutation(({ authorizationId, note }: { authorizationId: number; note: string }) =>
    unwrap(
      api.POST("/api/orders/perform-first/{authorization_id}/revoke", {
        params: { path: { authorization_id: authorizationId } },
        body: { note },
      }),
    ),
  );
}
