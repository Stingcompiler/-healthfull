/**
 * TanStack Query hooks of the claims module (ARCHITECTURE 5.5). Every rule is the server's:
 * these hooks only fetch, send and refresh what the screens show.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";

import type {
  ClaimBuildIn,
  ClaimPayerPaymentIn,
  ClaimResolveIn,
  ClaimResponseIn,
  ClaimShortfallIn,
  ClaimStatus,
} from "./types";

export const claimsKeys = {
  all: ["claims"] as const,
  options: ["claims", "options"] as const,
  receivables: ["claims", "receivables"] as const,
  aging: ["claims", "aging"] as const,
  accrued: (payerId: number, start: string, end: string) => ["claims", "accrued", payerId, start, end] as const,
  list: (filters: { payerId?: number; status?: ClaimStatus; page: number }) => ["claims", "list", filters] as const,
  detail: (claimId: number) => ["claims", "detail", claimId] as const,
  print: (claimId: number) => ["claims", "print", claimId] as const,
  payable: (payerId: number) => ["claims", "payable", payerId] as const,
  payments: (filters: { payerId?: number; standing?: PaymentFilter; page: number }) =>
    ["claims", "payments", filters] as const,
};

export type PaymentFilter = "cheque_pending" | "reversed";

/** Page size of the claim lists. */
export const PAGE_SIZE = 25;

/** The download address of a claim's Excel workbook (a plain link: the session cookie goes with it). */
export function exportUrl(claimId: number, language: "ar" | "en"): string {
  return `/api/claims/batches/${String(claimId)}/export?language=${language}`;
}

// --- reads ------------------------------------------------------------------------------------

export function useClaimOptions() {
  return useQuery({
    queryKey: claimsKeys.options,
    queryFn: () => unwrap(api.GET("/api/claims/options")),
    staleTime: 60_000,
  });
}

export function useReceivables() {
  return useQuery({
    queryKey: claimsKeys.receivables,
    queryFn: () => unwrap(api.GET("/api/claims/receivables")),
  });
}

export function useAging() {
  return useQuery({
    queryKey: claimsKeys.aging,
    queryFn: () => unwrap(api.GET("/api/claims/aging")),
  });
}

export function useAccrued(payerId: number | undefined, start: string, end: string) {
  return useQuery({
    queryKey: claimsKeys.accrued(payerId ?? 0, start, end),
    queryFn: () =>
      unwrap(
        api.GET("/api/claims/accrued", {
          params: {
            query: { payer_id: payerId ?? 0, period_start: start || null, period_end: end || null },
          },
        }),
      ),
    enabled: payerId !== undefined,
    placeholderData: keepPreviousData,
  });
}

export function useClaims(filters: { payerId?: number; status?: ClaimStatus; page: number }) {
  return useQuery({
    queryKey: claimsKeys.list(filters),
    queryFn: () =>
      unwrap(
        api.GET("/api/claims/batches", {
          params: {
            query: {
              payer_id: filters.payerId ?? null,
              status: filters.status ?? null,
              page: filters.page,
              page_size: PAGE_SIZE,
            },
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

export function useClaim(claimId: number) {
  return useQuery({
    queryKey: claimsKeys.detail(claimId),
    queryFn: () => unwrap(api.GET("/api/claims/batches/{claim_id}", { params: { path: { claim_id: claimId } } })),
  });
}

export function useClaimPrint(claimId: number) {
  return useQuery({
    queryKey: claimsKeys.print(claimId),
    queryFn: () => unwrap(api.GET("/api/claims/batches/{claim_id}/print", { params: { path: { claim_id: claimId } } })),
  });
}

export function usePayable(payerId: number | undefined) {
  return useQuery({
    queryKey: claimsKeys.payable(payerId ?? 0),
    queryFn: () =>
      unwrap(api.GET("/api/claims/payers/{payer_id}/payable", { params: { path: { payer_id: payerId ?? 0 } } })),
    enabled: payerId !== undefined,
    staleTime: 0,
  });
}

export function usePayerPayments(filters: { payerId?: number; standing?: PaymentFilter; page: number }) {
  return useQuery({
    queryKey: claimsKeys.payments(filters),
    queryFn: () =>
      unwrap(
        api.GET("/api/claims/payer-payments", {
          params: {
            query: {
              payer_id: filters.payerId ?? null,
              standing: filters.standing ?? null,
              page: filters.page,
              page_size: PAGE_SIZE,
            },
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

// --- commands ---------------------------------------------------------------------------------

/** Every claims mutation refreshes the module's cached reads (receivables, aging, lists). */
function useClaimsMutation<TArgs, TResult>(fn: (args: TArgs) => Promise<TResult>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: claimsKeys.all });
    },
  });
}

const path = (claimId: number) => ({ params: { path: { claim_id: claimId } } });
const linePath = (claimId: number, lineId: number) => ({ params: { path: { claim_id: claimId, line_id: lineId } } });

export function useBuildClaim() {
  return useClaimsMutation((body: ClaimBuildIn) => unwrap(api.POST("/api/claims/batches", { body })));
}

export function useRemoveClaimLine() {
  return useClaimsMutation(({ claimId, lineId }: { claimId: number; lineId: number }) =>
    unwrap(api.DELETE("/api/claims/batches/{claim_id}/lines/{line_id}", linePath(claimId, lineId))),
  );
}

export function useSubmitClaim() {
  return useClaimsMutation((claimId: number) =>
    unwrap(api.POST("/api/claims/batches/{claim_id}/submit", path(claimId))),
  );
}

export function useVoidClaim() {
  return useClaimsMutation(({ claimId, note }: { claimId: number; note: string }) =>
    unwrap(api.POST("/api/claims/batches/{claim_id}/void", { ...path(claimId), body: { note } })),
  );
}

export function useCloseClaim() {
  return useClaimsMutation((claimId: number) =>
    unwrap(api.POST("/api/claims/batches/{claim_id}/close", path(claimId))),
  );
}

export function useRecordResponses() {
  return useClaimsMutation(({ claimId, responses }: { claimId: number; responses: ClaimResponseIn[] }) =>
    unwrap(api.POST("/api/claims/batches/{claim_id}/responses", { ...path(claimId), body: { responses } })),
  );
}

export function useResolveRejection() {
  return useClaimsMutation(({ claimId, lineId, body }: { claimId: number; lineId: number; body: ClaimResolveIn }) =>
    unwrap(api.POST("/api/claims/batches/{claim_id}/lines/{line_id}/resolve", { ...linePath(claimId, lineId), body })),
  );
}

export function useWriteOffShortfall() {
  return useClaimsMutation(({ claimId, lineId, body }: { claimId: number; lineId: number; body: ClaimShortfallIn }) =>
    unwrap(
      api.POST("/api/claims/batches/{claim_id}/lines/{line_id}/write-off", { ...linePath(claimId, lineId), body }),
    ),
  );
}

export function useRecordPayerPayment() {
  return useClaimsMutation((body: ClaimPayerPaymentIn) => unwrap(api.POST("/api/claims/payer-payments", { body })));
}

export function useClearCheque() {
  return useClaimsMutation(({ paymentId, note }: { paymentId: number; note: string }) =>
    unwrap(
      api.POST("/api/claims/payer-payments/{payment_id}/clear", {
        params: { path: { payment_id: paymentId } },
        body: { note },
      }),
    ),
  );
}

export function useReversePayerPayment() {
  return useClaimsMutation(({ paymentId, note }: { paymentId: number; note: string }) =>
    unwrap(
      api.POST("/api/claims/payer-payments/{payment_id}/reverse", {
        params: { path: { payment_id: paymentId } },
        body: { note },
      }),
    ),
  );
}
