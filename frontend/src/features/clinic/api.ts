/** TanStack Query hooks over /api/clinical and /api/orders (ARCHITECTURE 5.5). No business rules. */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";

import type {
  EstimateInput,
  AllergyInput,
  AllergyPatch,
  ConditionInput,
  ConditionPatch,
  DiagnosisInput,
  NoteInput,
  NotePatch,
  OrderableKind,
  OrderInput,
  OrderSetInput,
  PrescriptionPreviewInput,
  QueueAction,
  ReferralInput,
  VitalsInput,
} from "./types";

export const clinicKeys = {
  all: ["clinic"] as const,
  worklist: ["clinic", "worklist"] as const,
  workspace: (visitId: number) => ["clinic", "workspace", visitId] as const,
  summary: (patientId: number) => ["clinic", "summary", patientId] as const,
  history: (patientId: number) => ["clinic", "history", patientId] as const,
  results: (patientId: number) => ["clinic", "results", patientId] as const,
  allergies: (patientId: number) => ["clinic", "allergies", patientId] as const,
  conditions: (patientId: number) => ["clinic", "conditions", patientId] as const,
  drugClasses: ["clinic", "drug-classes"] as const,
  icd10: (q: string) => ["clinic", "icd10", q] as const,
  referralTargets: ["clinic", "referral-targets"] as const,
  orderSets: ["clinic", "order-sets"] as const,
  lines: (visitId: number) => ["clinic", "lines", visitId] as const,
  catalog: (q: string, kind: OrderableKind | null) => ["clinic", "catalog", q, kind] as const,
  frequencies: ["clinic", "frequencies"] as const,
  preview: (input: PrescriptionPreviewInput) => ["clinic", "preview", input] as const,
  withdrawReasons: ["clinic", "withdraw-reasons"] as const,
};

/** The doctor's queue changes as the cashier and reception work. */
export const WORKLIST_REFRESH_MS = 10_000;
/** Order statuses change as the cashier, lab and pharmacy work. */
export const LINES_REFRESH_MS = 15_000;

const REFERENCE_STALE_MS = 10 * 60_000;

// --- queue ------------------------------------------------------------------------------------

export function useWorklist() {
  return useQuery({
    queryKey: clinicKeys.worklist,
    queryFn: () => unwrap(api.GET("/api/clinical/worklist")),
    refetchInterval: WORKLIST_REFRESH_MS,
  });
}

export function useCallNext() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/clinical/worklist/call-next")),
    onSettled: () => qc.invalidateQueries({ queryKey: clinicKeys.worklist }),
  });
}

export function useQueueAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ entryId, action }: { entryId: number; action: QueueAction }) =>
      unwrap(
        api.POST("/api/clinical/worklist/{entry_id}/action", {
          params: { path: { entry_id: entryId } },
          body: { action },
        }),
      ),
    onSettled: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: clinicKeys.worklist }),
        qc.invalidateQueries({ queryKey: ["clinic", "workspace"] }),
      ]),
  });
}

// --- workspace and summary --------------------------------------------------------------------

export function useWorkspace(visitId: number) {
  return useQuery({
    queryKey: clinicKeys.workspace(visitId),
    queryFn: () =>
      unwrap(api.GET("/api/clinical/visits/{visit_id}/workspace", { params: { path: { visit_id: visitId } } })),
  });
}

export function usePatientSummary(patientId: number | undefined) {
  return useQuery({
    queryKey: clinicKeys.summary(patientId ?? 0),
    queryFn: () =>
      unwrap(
        api.GET("/api/clinical/patients/{patient_id}/summary", { params: { path: { patient_id: patientId ?? 0 } } }),
      ),
    enabled: patientId !== undefined,
  });
}

export function useHistory(patientId: number, enabled: boolean) {
  return useQuery({
    queryKey: clinicKeys.history(patientId),
    queryFn: () =>
      unwrap(api.GET("/api/clinical/patients/{patient_id}/history", { params: { path: { patient_id: patientId } } })),
    enabled,
  });
}

export function useResults(patientId: number, enabled: boolean) {
  return useQuery({
    queryKey: clinicKeys.results(patientId),
    queryFn: () =>
      unwrap(
        api.GET("/api/clinical/patients/{patient_id}/results", {
          params: { path: { patient_id: patientId }, query: { limit: 50 } },
        }),
      ),
    enabled,
  });
}

// --- allergies and conditions ----------------------------------------------------------------

function useInvalidatePatient() {
  const qc = useQueryClient();
  return (patientId: number) =>
    Promise.all([
      qc.invalidateQueries({ queryKey: clinicKeys.summary(patientId) }),
      qc.invalidateQueries({ queryKey: clinicKeys.allergies(patientId) }),
      qc.invalidateQueries({ queryKey: clinicKeys.conditions(patientId) }),
      qc.invalidateQueries({ queryKey: clinicKeys.worklist }),
      qc.invalidateQueries({ queryKey: ["clinic", "workspace"] }),
    ]);
}

export function useAllergies(patientId: number, enabled: boolean) {
  return useQuery({
    queryKey: clinicKeys.allergies(patientId),
    queryFn: () =>
      unwrap(api.GET("/api/clinical/patients/{patient_id}/allergies", { params: { path: { patient_id: patientId } } })),
    enabled,
  });
}

export function useConditions(patientId: number, enabled: boolean) {
  return useQuery({
    queryKey: clinicKeys.conditions(patientId),
    queryFn: () =>
      unwrap(
        api.GET("/api/clinical/patients/{patient_id}/conditions", { params: { path: { patient_id: patientId } } }),
      ),
    enabled,
  });
}

export function useDrugClasses(enabled: boolean) {
  return useQuery({
    queryKey: clinicKeys.drugClasses,
    queryFn: () => unwrap(api.GET("/api/clinical/drug-classes")),
    staleTime: REFERENCE_STALE_MS,
    enabled,
  });
}

export function useCreateAllergy(patientId: number) {
  const invalidate = useInvalidatePatient();
  return useMutation({
    mutationFn: (body: AllergyInput) =>
      unwrap(
        api.POST("/api/clinical/patients/{patient_id}/allergies", {
          params: { path: { patient_id: patientId } },
          body,
        }),
      ),
    onSuccess: () => invalidate(patientId),
  });
}

export function useUpdateAllergy(patientId: number) {
  const invalidate = useInvalidatePatient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: AllergyPatch }) =>
      unwrap(api.PATCH("/api/clinical/allergies/{allergy_id}", { params: { path: { allergy_id: id } }, body })),
    onSuccess: () => invalidate(patientId),
  });
}

export function useCreateCondition(patientId: number) {
  const invalidate = useInvalidatePatient();
  return useMutation({
    mutationFn: (body: ConditionInput) =>
      unwrap(
        api.POST("/api/clinical/patients/{patient_id}/conditions", {
          params: { path: { patient_id: patientId } },
          body,
        }),
      ),
    onSuccess: () => invalidate(patientId),
  });
}

export function useUpdateCondition(patientId: number) {
  const invalidate = useInvalidatePatient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: ConditionPatch }) =>
      unwrap(api.PATCH("/api/clinical/conditions/{condition_id}", { params: { path: { condition_id: id } }, body })),
    onSuccess: () => invalidate(patientId),
  });
}

// --- notes, diagnoses, vitals, referrals ------------------------------------------------------

export function useIcd10Search(q: string) {
  const term = q.trim();
  return useQuery({
    queryKey: clinicKeys.icd10(term),
    queryFn: () => unwrap(api.GET("/api/clinical/icd10", { params: { query: { q: term, limit: 15 } } })),
    enabled: term.length >= 2,
    staleTime: REFERENCE_STALE_MS,
    placeholderData: keepPreviousData,
  });
}

function useInvalidateWorkspace(visitId: number) {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: clinicKeys.workspace(visitId) });
}

export function useCreateNote(visitId: number) {
  const invalidate = useInvalidateWorkspace(visitId);
  return useMutation({
    mutationFn: (body: NoteInput) =>
      unwrap(api.POST("/api/clinical/visits/{visit_id}/notes", { params: { path: { visit_id: visitId } }, body })),
    onSuccess: invalidate,
  });
}

export function useUpdateNote(visitId: number) {
  const invalidate = useInvalidateWorkspace(visitId);
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: NotePatch }) =>
      unwrap(api.PATCH("/api/clinical/notes/{note_id}", { params: { path: { note_id: id } }, body })),
    onSuccess: invalidate,
  });
}

export function useSignNote(visitId: number) {
  const invalidate = useInvalidateWorkspace(visitId);
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(api.POST("/api/clinical/notes/{note_id}/sign", { params: { path: { note_id: id } } })),
    onSuccess: invalidate,
  });
}

export function useCreateDiagnosis(visitId: number) {
  const invalidate = useInvalidateWorkspace(visitId);
  return useMutation({
    mutationFn: (body: DiagnosisInput) =>
      unwrap(api.POST("/api/clinical/visits/{visit_id}/diagnoses", { params: { path: { visit_id: visitId } }, body })),
    onSuccess: invalidate,
  });
}

export function useDeleteDiagnosis(visitId: number) {
  const invalidate = useInvalidateWorkspace(visitId);
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(api.DELETE("/api/clinical/diagnoses/{diagnosis_id}", { params: { path: { diagnosis_id: id } } })),
    onSuccess: invalidate,
  });
}

export function useCreateVitals(visitId: number) {
  const invalidate = useInvalidateWorkspace(visitId);
  return useMutation({
    mutationFn: (body: VitalsInput) =>
      unwrap(api.POST("/api/clinical/visits/{visit_id}/vitals", { params: { path: { visit_id: visitId } }, body })),
    onSuccess: invalidate,
  });
}

export function useReferralTargets(enabled: boolean) {
  return useQuery({
    queryKey: clinicKeys.referralTargets,
    queryFn: () => unwrap(api.GET("/api/clinical/referral-targets")),
    staleTime: REFERENCE_STALE_MS,
    enabled,
  });
}

export function useCreateReferral(visitId: number) {
  const invalidate = useInvalidateWorkspace(visitId);
  return useMutation({
    mutationFn: (body: ReferralInput) =>
      unwrap(api.POST("/api/clinical/visits/{visit_id}/referrals", { params: { path: { visit_id: visitId } }, body })),
    onSuccess: invalidate,
  });
}

export function useCancelReferral(visitId: number) {
  const invalidate = useInvalidateWorkspace(visitId);
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(api.POST("/api/clinical/referrals/{referral_id}/cancel", { params: { path: { referral_id: id } } })),
    onSuccess: invalidate,
  });
}

// --- order sets, catalog, prescriptions -------------------------------------------------------

export function useOrderSets() {
  return useQuery({
    queryKey: clinicKeys.orderSets,
    queryFn: () => unwrap(api.GET("/api/clinical/order-sets")),
  });
}

export function useCreateFavorite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: OrderSetInput) => unwrap(api.POST("/api/clinical/order-sets", { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: clinicKeys.orderSets }),
  });
}

export function useDeleteFavorite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(api.DELETE("/api/clinical/order-sets/{order_set_id}", { params: { path: { order_set_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: clinicKeys.orderSets }),
  });
}

export function useCatalog(q: string, kind: OrderableKind | null) {
  const term = q.trim();
  return useQuery({
    queryKey: clinicKeys.catalog(term, kind),
    queryFn: () =>
      unwrap(api.GET("/api/orders/catalog", { params: { query: { q: term, kind: kind ?? undefined, limit: 20 } } })),
    enabled: term.length >= 1,
    placeholderData: keepPreviousData,
    staleTime: REFERENCE_STALE_MS,
  });
}

export function useFrequencies() {
  return useQuery({
    queryKey: clinicKeys.frequencies,
    queryFn: () => unwrap(api.GET("/api/orders/frequencies")),
    staleTime: Infinity,
  });
}

/** The quantity a prescription orders, computed by the server (never in the browser). */
export function usePrescriptionPreview(input: PrescriptionPreviewInput, enabled: boolean) {
  return useQuery({
    queryKey: clinicKeys.preview(input),
    queryFn: () => unwrap(api.POST("/api/orders/prescription-preview", { body: input })),
    enabled,
    staleTime: Infinity,
    retry: false,
  });
}

// --- orders -----------------------------------------------------------------------------------

export function useVisitLines(visitId: number) {
  return useQuery({
    queryKey: clinicKeys.lines(visitId),
    queryFn: () => unwrap(api.GET("/api/orders/visits/{visit_id}/lines", { params: { path: { visit_id: visitId } } })),
    refetchInterval: LINES_REFRESH_MS,
  });
}

export function useCreateLines(visitId: number, patientId: number | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: OrderInput) =>
      unwrap(api.POST("/api/orders/visits/{visit_id}/lines", { params: { path: { visit_id: visitId } }, body })),
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: clinicKeys.lines(visitId) }),
        patientId ? qc.invalidateQueries({ queryKey: clinicKeys.summary(patientId) }) : null,
      ]),
  });
}

export function useWithdrawReasons(enabled: boolean) {
  return useQuery({
    queryKey: clinicKeys.withdrawReasons,
    queryFn: () => unwrap(api.GET("/api/orders/withdraw-reasons")),
    staleTime: REFERENCE_STALE_MS,
    enabled,
  });
}

export function useWithdrawLine(visitId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ lineId, reasonCode, note }: { lineId: number; reasonCode: string; note: string }) =>
      unwrap(
        api.POST("/api/orders/lines/{line_id}/withdraw", {
          params: { path: { line_id: lineId } },
          body: { reason_code: reasonCode, note },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: clinicKeys.lines(visitId) }),
  });
}

/** The patient's estimated share of a draft order (FEATURES 3.8): only when the center allows it. */
export function useEstimate(visitId: number) {
  return useMutation({
    mutationFn: (body: EstimateInput) =>
      unwrap(api.POST("/api/orders/visits/{visit_id}/estimate", { params: { path: { visit_id: visitId } }, body })),
  });
}
