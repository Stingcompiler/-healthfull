/**
 * TanStack Query hooks of the system pages under /administration (ARCHITECTURE 5.5):
 * Excel imports of every kind, system status and manual backups, update history, the full
 * data export and the audit trail. Every call goes through the typed client; the server
 * validates and decides, the screens only show its answers.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";

import type { AuditAction, ImportKind, ImportRowStatus } from "./ops-types";

export const opsKeys = {
  importJobs: (kind: ImportKind | null) => ["ops", "imports", "jobs", kind] as const,
  importRows: (id: number, status: string | null, page: number) =>
    ["ops", "imports", "rows", id, status, page] as const,
  status: ["ops", "status"] as const,
  updates: (page: number) => ["ops", "updates", page] as const,
  auditModels: ["ops", "audit", "models"] as const,
  audit: (filters: AuditFilters) => ["ops", "audit", "events", filters] as const,
  importStores: ["ops", "imports", "stores"] as const,
  importPriceLists: ["ops", "imports", "price-lists"] as const,
};

/** Rows one page of the import preview shows. */
export const IMPORT_PAGE_SIZE = 25;
export const AUDIT_PAGE_SIZE = 25;

export type ImportRowFilter = "problems" | ImportRowStatus;

export interface ImportUpload {
  kind: ImportKind;
  file: File;
  store?: string;
  priceList?: string;
  effectiveFrom?: string;
}

/** Upload a sheet: the server reads and checks every row; nothing is imported yet. */
export function usePreviewImportJob() {
  return useMutation({
    mutationFn: (upload: ImportUpload) =>
      unwrap(
        api.POST("/api/imports/jobs", {
          body: { file: upload.file as unknown as string, kind: upload.kind },
          bodySerializer: () => {
            const form = new FormData();
            form.append("file", upload.file, upload.file.name);
            form.append("kind", upload.kind);
            if (upload.store) form.append("store", upload.store);
            if (upload.priceList) form.append("price_list", upload.priceList);
            if (upload.effectiveFrom) form.append("effective_from", upload.effectiveFrom);
            return form;
          },
        }),
      ),
  });
}

export function useImportJobRows(jobId: number | null, status: ImportRowFilter | null, page: number) {
  return useQuery({
    queryKey: opsKeys.importRows(jobId ?? 0, status, page),
    queryFn: () =>
      unwrap(
        api.GET("/api/imports/jobs/{job_id}/rows", {
          params: {
            path: { job_id: jobId ?? 0 },
            query: { status: status ?? undefined, page, page_size: IMPORT_PAGE_SIZE },
          },
        }),
      ),
    enabled: jobId !== null,
    placeholderData: keepPreviousData,
  });
}

export function useImportJobs(kind: ImportKind | null) {
  return useQuery({
    queryKey: opsKeys.importJobs(kind),
    queryFn: () =>
      unwrap(api.GET("/api/imports/jobs", { params: { query: { kind: kind ?? undefined, page_size: 10 } } })),
  });
}

export function useConfirmImportJob() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, includeDuplicates }: { jobId: number; includeDuplicates: boolean }) =>
      unwrap(
        api.POST("/api/imports/{job_id}/confirm", {
          params: { path: { job_id: jobId } },
          body: { include_duplicates: includeDuplicates },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["ops", "imports"] }),
  });
}

export function useCancelImportJob() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (jobId: number) =>
      unwrap(api.POST("/api/imports/{job_id}/cancel", { params: { path: { job_id: jobId } } })),
    onSuccess: () => client.invalidateQueries({ queryKey: ["ops", "imports", "jobs"] }),
  });
}

/** Stores for the opening stock of an item import (the pharmacy's reference lists). */
export function useImportStores(enabled: boolean) {
  return useQuery({
    queryKey: opsKeys.importStores,
    queryFn: () => unwrap(api.GET("/api/pharmacy/options")),
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function useImportPriceLists(enabled: boolean) {
  return useQuery({
    queryKey: opsKeys.importPriceLists,
    queryFn: () => unwrap(api.GET("/api/catalog/price-lists")),
    enabled,
    staleTime: 60_000,
  });
}

// --- status, backups, updates ---------------------------------------------------------------

export function useSystemStatus() {
  return useQuery({ queryKey: opsKeys.status, queryFn: () => unwrap(api.GET("/api/ops/status")) });
}

export function useRequestBackup() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (note: string) => unwrap(api.POST("/api/ops/backups/request", { body: { note } })),
    onSettled: () => client.invalidateQueries({ queryKey: opsKeys.status }),
  });
}

export function useUpdateHistory(page: number) {
  return useQuery({
    queryKey: opsKeys.updates(page),
    queryFn: () => unwrap(api.GET("/api/ops/updates", { params: { query: { page, page_size: 10 } } })),
    placeholderData: keepPreviousData,
  });
}

// --- data export ----------------------------------------------------------------------------

/** The zip archive of the full export (a POST: every export is recorded on the server). */
export function useExportData() {
  return useMutation({
    mutationFn: async () => {
      const result = await api.POST("/api/ops/export", { parseAs: "blob" });
      const blob = await unwrap(Promise.resolve(result));
      const disposition = result.response.headers.get("Content-Disposition") ?? "";
      const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "hospital-export.zip";
      return { blob, name };
    },
  });
}

// --- audit ----------------------------------------------------------------------------------

export interface AuditFilters {
  model: string | null;
  userId: number | null;
  dateFrom: string | null;
  dateTo: string | null;
  objectId: string | null;
  action: AuditAction | null;
  page: number;
}

export function useAuditModels() {
  return useQuery({
    queryKey: opsKeys.auditModels,
    queryFn: () => unwrap(api.GET("/api/core/audit/models")),
    staleTime: 10 * 60_000,
  });
}

export function useAuditEvents(filters: AuditFilters) {
  return useQuery({
    queryKey: opsKeys.audit(filters),
    queryFn: () =>
      unwrap(
        api.GET("/api/core/audit/events", {
          params: {
            query: {
              model: filters.model ?? undefined,
              user_id: filters.userId ?? undefined,
              date_from: filters.dateFrom ?? undefined,
              date_to: filters.dateTo ?? undefined,
              object_id: filters.objectId ?? undefined,
              action: filters.action ?? undefined,
              page: filters.page,
              page_size: AUDIT_PAGE_SIZE,
            },
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}
