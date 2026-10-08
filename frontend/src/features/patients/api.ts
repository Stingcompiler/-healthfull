/** TanStack Query hooks over /api/patients (ARCHITECTURE 5.5). No business rules here. */
import { keepPreviousData, queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";

import type {
  CoverageInput,
  CoveragePatch,
  DuplicateQuery,
  EmergencyInput,
  MergeInput,
  PatientInput,
  PatientPatch,
} from "./types";

export const patientKeys = {
  all: ["patients"] as const,
  list: (q: string, page: number, pageSize: number, incomplete: boolean) =>
    ["patients", "list", { q, page, pageSize, incomplete }] as const,
  duplicates: (query: DuplicateQuery) => ["patients", "duplicates", query] as const,
  detail: (id: number) => ["patients", "detail", id] as const,
  coverages: (id: number, includeInactive: boolean) => ["patients", "coverages", id, includeInactive] as const,
  merges: (id: number) => ["patients", "merges", id] as const,
  balance: (id: number) => ["patients", "balance", id] as const,
  payers: ["patients", "payers"] as const,
  mergeReasons: ["patients", "merge-reasons"] as const,
};

export interface PatientListQuery {
  q: string;
  page: number;
  pageSize: number;
  incomplete?: boolean;
}

export function patientListOptions({ q, page, pageSize, incomplete = false }: PatientListQuery) {
  return queryOptions({
    queryKey: patientKeys.list(q, page, pageSize, incomplete),
    queryFn: () =>
      unwrap(
        api.GET("/api/patients", {
          params: { query: { q: q || undefined, page, page_size: pageSize, incomplete } },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

export function usePatientList(query: PatientListQuery, enabled = true) {
  return useQuery({ ...patientListOptions(query), enabled });
}

/** Live duplicate warning while the registration form is typed (FEATURES 1.3). */
export function useDuplicates(query: DuplicateQuery, enabled: boolean) {
  return useQuery({
    queryKey: patientKeys.duplicates(query),
    queryFn: () => unwrap(api.GET("/api/patients/duplicates", { params: { query } })),
    enabled,
    staleTime: 10_000,
  });
}

export function usePatient(id: number) {
  return useQuery({
    queryKey: patientKeys.detail(id),
    queryFn: () => unwrap(api.GET("/api/patients/{patient_id}", { params: { path: { patient_id: id } } })),
  });
}

export function useCoverages(id: number, includeInactive = false, enabled = true) {
  return useQuery({
    enabled,
    queryKey: patientKeys.coverages(id, includeInactive),
    queryFn: () =>
      unwrap(
        api.GET("/api/patients/{patient_id}/coverages", {
          params: { path: { patient_id: id }, query: { include_inactive: includeInactive } },
        }),
      ),
  });
}

export function useMerges(id: number) {
  return useQuery({
    queryKey: patientKeys.merges(id),
    queryFn: () => unwrap(api.GET("/api/patients/{patient_id}/merges", { params: { path: { patient_id: id } } })),
  });
}

export function useBalance(id: number, enabled: boolean) {
  return useQuery({
    queryKey: patientKeys.balance(id),
    queryFn: () => unwrap(api.GET("/api/patients/{patient_id}/balance", { params: { path: { patient_id: id } } })),
    enabled,
  });
}

/** The configurable merge reasons (ReasonCode rows, FEATURES 13.5). */
export function useMergeReasons(enabled = true) {
  return useQuery({
    queryKey: patientKeys.mergeReasons,
    queryFn: () => unwrap(api.GET("/api/patients/merge-reasons")),
    staleTime: 5 * 60_000,
    enabled,
  });
}

export function usePayers(enabled = true) {
  return useQuery({
    queryKey: patientKeys.payers,
    queryFn: () => unwrap(api.GET("/api/patients/payers")),
    staleTime: 5 * 60_000,
    enabled,
  });
}

function useInvalidatePatients() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: patientKeys.all });
}

export function useCreatePatient() {
  const invalidate = useInvalidatePatients();
  return useMutation({
    mutationFn: (body: PatientInput) => unwrap(api.POST("/api/patients", { body })),
    onSuccess: invalidate,
  });
}

export function useRegisterEmergency() {
  const invalidate = useInvalidatePatients();
  return useMutation({
    mutationFn: (body: EmergencyInput) => unwrap(api.POST("/api/patients/emergency", { body })),
    onSuccess: invalidate,
  });
}

export function useUpdatePatient(id: number) {
  const invalidate = useInvalidatePatients();
  return useMutation({
    mutationFn: (body: PatientPatch) =>
      unwrap(api.PATCH("/api/patients/{patient_id}", { params: { path: { patient_id: id } }, body })),
    onSuccess: invalidate,
  });
}

/** Merge `duplicate_id` into the surviving file `id` (FEATURES 1.4). */
export function useMergePatient(id: number) {
  const invalidate = useInvalidatePatients();
  return useMutation({
    mutationFn: (body: MergeInput) =>
      unwrap(api.POST("/api/patients/{patient_id}/merge", { params: { path: { patient_id: id } }, body })),
    onSuccess: invalidate,
  });
}

export function useAddCoverage(id: number) {
  const invalidate = useInvalidatePatients();
  return useMutation({
    mutationFn: (body: CoverageInput) =>
      unwrap(api.POST("/api/patients/{patient_id}/coverages", { params: { path: { patient_id: id } }, body })),
    onSuccess: invalidate,
  });
}

export function useUpdateCoverage() {
  const invalidate = useInvalidatePatients();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: CoveragePatch }) =>
      unwrap(api.PATCH("/api/patients/coverages/{coverage_id}", { params: { path: { coverage_id: id } }, body })),
    onSuccess: invalidate,
  });
}

export function useEndCoverage() {
  const invalidate = useInvalidatePatients();
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(api.POST("/api/patients/coverages/{coverage_id}/end", { params: { path: { coverage_id: id } } })),
    onSuccess: invalidate,
  });
}

// --- Excel import of patients (FEATURES 1.8, /api/imports) ------------------------------------

export const importKeys = {
  job: (id: number) => ["imports", "job", id] as const,
  rows: (id: number, status: ImportRowFilter | null) => ["imports", "rows", id, status] as const,
};

export type ImportRowFilter = "problems" | "valid" | "error" | "duplicate" | "imported" | "skipped";

/** Most rows one request returns; the screen says when there are more. */
export const IMPORT_ROWS_SHOWN = 100;

/** Upload a sheet: the server validates every row and flags duplicates; nothing is saved. */
export function usePreviewImport() {
  return useMutation({
    mutationFn: (file: File) =>
      unwrap(
        api.POST("/api/imports/patients", {
          body: { file: file as unknown as string },
          bodySerializer: (body) => {
            const form = new FormData();
            form.append("file", body.file as unknown as Blob, file.name);
            return form;
          },
        }),
      ),
  });
}

export function useImportRows(jobId: number | null, status: ImportRowFilter | null) {
  return useQuery({
    queryKey: importKeys.rows(jobId ?? 0, status),
    queryFn: () =>
      unwrap(
        api.GET("/api/imports/{job_id}/rows", {
          params: {
            path: { job_id: jobId ?? 0 },
            query: { status: status ?? undefined, page: 1, page_size: IMPORT_ROWS_SHOWN },
          },
        }),
      ),
    enabled: jobId !== null,
  });
}

export function useConfirmImport() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, includeDuplicates }: { jobId: number; includeDuplicates: boolean }) =>
      unwrap(
        api.POST("/api/imports/{job_id}/confirm", {
          params: { path: { job_id: jobId } },
          body: { include_duplicates: includeDuplicates },
        }),
      ),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: ["imports"] }),
        client.invalidateQueries({ queryKey: patientKeys.all }),
      ]),
  });
}

export function useCancelImport() {
  return useMutation({
    mutationFn: (jobId: number) =>
      unwrap(api.POST("/api/imports/{job_id}/cancel", { params: { path: { job_id: jobId } } })),
  });
}
