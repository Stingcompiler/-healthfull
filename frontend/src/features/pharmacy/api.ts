/**
 * TanStack Query hooks of the pharmacy module (ARCHITECTURE 5.5). Every rule is the server's:
 * these hooks only fetch, send and refresh what the screens show.
 */
import { keepPreviousData, queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";

import type {
  AdjustmentStatus,
  CountStatus,
  DispenseIn,
  GoodsReceiptIn,
  PackUnitIn,
  PackUnitPatch,
  PharmacySaleIn,
  ReceiptStatus,
  StockAdjustmentIn,
  StockItemIn,
  StockItemPatch,
  StockTransferIn,
  SupplierIn,
  TransferReceiveIn,
  TransferStatus,
} from "./types";

export const pharmacyKeys = {
  all: ["pharmacy"] as const,
  options: ["pharmacy", "options"] as const,
  queue: (q: string) => ["pharmacy", "queue", q] as const,
  dispenseVisit: (visitId: number, storeId: number | undefined) =>
    ["pharmacy", "dispense-visit", visitId, storeId] as const,
  items: (q: string, low: boolean, page: number) => ["pharmacy", "items", q, low, page] as const,
  item: (itemId: number) => ["pharmacy", "item", itemId] as const,
  stockCard: (itemId: number, storeId: number | undefined) => ["pharmacy", "stock-card", itemId, storeId] as const,
  stockServices: ["pharmacy", "stock-services"] as const,
  storeBatches: (storeId: number, q: string) => ["pharmacy", "store-batches", storeId, q] as const,
  receipts: (status: ReceiptStatus | undefined, page: number) => ["pharmacy", "receipts", status, page] as const,
  adjustments: (status: AdjustmentStatus | undefined, page: number) =>
    ["pharmacy", "adjustments", status, page] as const,
  counts: (status: CountStatus | undefined, page: number) => ["pharmacy", "counts", status, page] as const,
  count: (countId: number) => ["pharmacy", "count", countId] as const,
  transfers: (status: TransferStatus | undefined, page: number) => ["pharmacy", "transfers", status, page] as const,
  expiry: (days: number, storeId: number | undefined) => ["pharmacy", "expiry", days, storeId] as const,
  lowStock: (storeId: number | undefined) => ["pharmacy", "low-stock", storeId] as const,
  saleServices: (q: string) => ["pharmacy", "sale-services", q] as const,
  saleCustomers: (q: string) => ["pharmacy", "sale-customers", q] as const,
};

/** Page size of the pharmacy lists. */
export const PAGE_SIZE = 25;

// --- reads ------------------------------------------------------------------------------------

export function usePharmacyOptions() {
  return useQuery({
    queryKey: pharmacyKeys.options,
    queryFn: () => unwrap(api.GET("/api/pharmacy/options")),
    staleTime: 5 * 60_000,
  });
}

/** The dispense queue for a typed or scanned term (shared by the list and Enter). */
export const queueQuery = (q: string) => {
  const term = q.trim();
  return queryOptions({
    queryKey: pharmacyKeys.queue(term),
    queryFn: () => unwrap(api.GET("/api/pharmacy/queue", { params: { query: { q: term || null } } })),
    staleTime: 0,
  });
};

export function useQueue(q: string) {
  return useQuery({ ...queueQuery(q), placeholderData: keepPreviousData, refetchInterval: 30_000 });
}

export function useDispenseVisit(visitId: number | undefined, storeId: number | undefined) {
  return useQuery({
    queryKey: pharmacyKeys.dispenseVisit(visitId ?? 0, storeId),
    queryFn: () =>
      unwrap(
        api.GET("/api/pharmacy/queue/visits/{visit_id}", {
          params: { path: { visit_id: visitId ?? 0 }, query: { store_id: storeId ?? null } },
        }),
      ),
    enabled: visitId !== undefined,
    staleTime: 0,
  });
}

export function useItems(q: string, low: boolean, page: number) {
  const term = q.trim();
  return useQuery({
    queryKey: pharmacyKeys.items(term, low, page),
    queryFn: () =>
      unwrap(
        api.GET("/api/pharmacy/items", {
          params: { query: { q: term || null, low, page, page_size: PAGE_SIZE } },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

export function useItem(itemId: number) {
  return useQuery({
    queryKey: pharmacyKeys.item(itemId),
    queryFn: () => unwrap(api.GET("/api/pharmacy/items/{item_id}", { params: { path: { item_id: itemId } } })),
  });
}

export function useStockCard(itemId: number, storeId: number | undefined) {
  return useQuery({
    queryKey: pharmacyKeys.stockCard(itemId, storeId),
    queryFn: () =>
      unwrap(
        api.GET("/api/pharmacy/items/{item_id}/stock-card", {
          params: { path: { item_id: itemId }, query: { store_id: storeId ?? null } },
        }),
      ),
  });
}

export function useStockServices(enabled: boolean) {
  return useQuery({
    queryKey: pharmacyKeys.stockServices,
    queryFn: () => unwrap(api.GET("/api/pharmacy/items/services")),
    enabled,
  });
}

export function useStoreBatches(storeId: number | undefined, q: string) {
  const term = q.trim();
  return useQuery({
    queryKey: pharmacyKeys.storeBatches(storeId ?? 0, term),
    queryFn: () =>
      unwrap(
        api.GET("/api/pharmacy/stores/{store_id}/batches", {
          params: { path: { store_id: storeId ?? 0 }, query: { q: term || null } },
        }),
      ),
    enabled: storeId !== undefined,
    placeholderData: keepPreviousData,
  });
}

export function useReceipts(status: ReceiptStatus | undefined, page: number) {
  return useQuery({
    queryKey: pharmacyKeys.receipts(status, page),
    queryFn: () =>
      unwrap(
        api.GET("/api/pharmacy/receipts", {
          params: { query: { status: status ?? null, page, page_size: PAGE_SIZE } },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

export function useAdjustments(status: AdjustmentStatus | undefined, page: number) {
  return useQuery({
    queryKey: pharmacyKeys.adjustments(status, page),
    queryFn: () =>
      unwrap(
        api.GET("/api/pharmacy/adjustments", {
          params: { query: { status: status ?? null, page, page_size: PAGE_SIZE } },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

export function useCounts(status: CountStatus | undefined, page: number) {
  return useQuery({
    queryKey: pharmacyKeys.counts(status, page),
    queryFn: () =>
      unwrap(
        api.GET("/api/pharmacy/counts", {
          params: { query: { status: status ?? null, page, page_size: PAGE_SIZE } },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

export function useCount(countId: number) {
  return useQuery({
    queryKey: pharmacyKeys.count(countId),
    queryFn: () => unwrap(api.GET("/api/pharmacy/counts/{count_id}", { params: { path: { count_id: countId } } })),
  });
}

export function useTransfers(status: TransferStatus | undefined, page: number) {
  return useQuery({
    queryKey: pharmacyKeys.transfers(status, page),
    queryFn: () =>
      unwrap(
        api.GET("/api/pharmacy/transfers", {
          params: { query: { status: status ?? null, page, page_size: PAGE_SIZE } },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

export function useExpiry(days: number, storeId: number | undefined) {
  return useQuery({
    queryKey: pharmacyKeys.expiry(days, storeId),
    queryFn: () =>
      unwrap(api.GET("/api/pharmacy/reports/expiry", { params: { query: { days, store_id: storeId ?? null } } })),
    placeholderData: keepPreviousData,
  });
}

export function useLowStock(storeId: number | undefined) {
  return useQuery({
    queryKey: pharmacyKeys.lowStock(storeId),
    queryFn: () =>
      unwrap(api.GET("/api/pharmacy/reports/low-stock", { params: { query: { store_id: storeId ?? null } } })),
    placeholderData: keepPreviousData,
  });
}

export function useSaleServices(q: string) {
  const term = q.trim();
  return useQuery({
    queryKey: pharmacyKeys.saleServices(term),
    queryFn: () => unwrap(api.GET("/api/pharmacy/sale/services", { params: { query: { q: term || null } } })),
    placeholderData: keepPreviousData,
  });
}

export function useSaleCustomers(q: string) {
  const term = q.trim();
  return useQuery({
    queryKey: pharmacyKeys.saleCustomers(term),
    queryFn: () => unwrap(api.GET("/api/pharmacy/sale/customers", { params: { query: { q: term } } })),
    enabled: term.length > 0,
    placeholderData: keepPreviousData,
  });
}

/** One lookup of a scanned barcode (not cached: every scan asks again). */
export function scanBarcode(code: string) {
  return unwrap(api.GET("/api/pharmacy/items/scan", { params: { query: { code } } }));
}

// --- writes -----------------------------------------------------------------------------------

function usePharmacyMutation<TVars, TData>(fn: (vars: TVars) => Promise<TData>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: pharmacyKeys.all });
    },
  });
}

export function useDispense() {
  return usePharmacyMutation((body: DispenseIn) => unwrap(api.POST("/api/pharmacy/dispenses", { body })));
}

export function useCreateItem() {
  return usePharmacyMutation((body: StockItemIn) => unwrap(api.POST("/api/pharmacy/items", { body })));
}

export function useUpdateItem() {
  return usePharmacyMutation(({ itemId, body }: { itemId: number; body: StockItemPatch }) =>
    unwrap(api.PATCH("/api/pharmacy/items/{item_id}", { params: { path: { item_id: itemId } }, body })),
  );
}

export function useAddUnit() {
  return usePharmacyMutation(({ itemId, body }: { itemId: number; body: PackUnitIn }) =>
    unwrap(api.POST("/api/pharmacy/items/{item_id}/units", { params: { path: { item_id: itemId } }, body })),
  );
}

export function useUpdateUnit() {
  return usePharmacyMutation(({ itemId, unitId, body }: { itemId: number; unitId: number; body: PackUnitPatch }) =>
    unwrap(
      api.PATCH("/api/pharmacy/items/{item_id}/units/{unit_id}", {
        params: { path: { item_id: itemId, unit_id: unitId } },
        body,
      }),
    ),
  );
}

export function useCreateSupplier() {
  return usePharmacyMutation((body: SupplierIn) => unwrap(api.POST("/api/pharmacy/suppliers", { body })));
}

export function useCreateReceipt() {
  return usePharmacyMutation((body: GoodsReceiptIn) => unwrap(api.POST("/api/pharmacy/receipts", { body })));
}

export function useReceiptAction() {
  return usePharmacyMutation(({ receiptId, action }: { receiptId: number; action: "post" | "cancel" }) =>
    action === "post"
      ? unwrap(api.POST("/api/pharmacy/receipts/{receipt_id}/post", { params: { path: { receipt_id: receiptId } } }))
      : unwrap(api.POST("/api/pharmacy/receipts/{receipt_id}/cancel", { params: { path: { receipt_id: receiptId } } })),
  );
}

export function useRequestAdjustment() {
  return usePharmacyMutation((body: StockAdjustmentIn) => unwrap(api.POST("/api/pharmacy/adjustments", { body })));
}

export function useDecideAdjustment() {
  return usePharmacyMutation(
    ({ adjustmentId, decision, note }: { adjustmentId: number; decision: "approve" | "reject"; note: string }) =>
      decision === "approve"
        ? unwrap(
            api.POST("/api/pharmacy/adjustments/{adjustment_id}/approve", {
              params: { path: { adjustment_id: adjustmentId } },
              body: { note },
            }),
          )
        : unwrap(
            api.POST("/api/pharmacy/adjustments/{adjustment_id}/reject", {
              params: { path: { adjustment_id: adjustmentId } },
              body: { note },
            }),
          ),
  );
}

export function useStartCount() {
  return usePharmacyMutation((body: { store_id: number; note: string }) =>
    unwrap(api.POST("/api/pharmacy/counts", { body })),
  );
}

export function useRecordCount() {
  return usePharmacyMutation(
    ({ countId, batchId, counted, note }: { countId: number; batchId: number; counted: number; note?: string }) =>
      unwrap(
        api.POST("/api/pharmacy/counts/{count_id}/record", {
          params: { path: { count_id: countId } },
          body: { batch_id: batchId, counted_qty: counted, note: note ?? "" },
        }),
      ),
  );
}

export function useCountAction() {
  return usePharmacyMutation(({ countId, action }: { countId: number; action: "post" | "cancel" }) =>
    action === "post"
      ? unwrap(api.POST("/api/pharmacy/counts/{count_id}/post", { params: { path: { count_id: countId } } }))
      : unwrap(api.POST("/api/pharmacy/counts/{count_id}/cancel", { params: { path: { count_id: countId } } })),
  );
}

export function useCreateTransfer() {
  return usePharmacyMutation((body: StockTransferIn) => unwrap(api.POST("/api/pharmacy/transfers", { body })));
}

export function useSendTransfer() {
  return usePharmacyMutation((transferId: number) =>
    unwrap(api.POST("/api/pharmacy/transfers/{transfer_id}/send", { params: { path: { transfer_id: transferId } } })),
  );
}

export function useReceiveTransfer() {
  return usePharmacyMutation(({ transferId, body }: { transferId: number; body: TransferReceiveIn }) =>
    unwrap(
      api.POST("/api/pharmacy/transfers/{transfer_id}/receive", {
        params: { path: { transfer_id: transferId } },
        body,
      }),
    ),
  );
}

export function useCancelTransfer() {
  return usePharmacyMutation(({ transferId, note }: { transferId: number; note: string }) =>
    unwrap(
      api.POST("/api/pharmacy/transfers/{transfer_id}/cancel", {
        params: { path: { transfer_id: transferId } },
        body: { note },
      }),
    ),
  );
}

export function useCreateSale() {
  return usePharmacyMutation((body: PharmacySaleIn) => unwrap(api.POST("/api/pharmacy/sales", { body })));
}
