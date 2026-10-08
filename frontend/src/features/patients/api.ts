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
