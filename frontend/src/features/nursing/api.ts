/**
 * TanStack Query hooks over /api/orders/procedures, /api/clinical/nursing and
 * /api/visits/inpatient (ARCHITECTURE 5.5). No business rules: the server decides what is
 * eligible, what a night costs and what a discharge charges.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";

import type { AdmitInput, CancelAdmissionInput, NursingNoteInput, VitalsInput } from "./types";

export const nursingKeys = {
  all: ["nursing"] as const,
  procedures: (q: string, department: number | null) => ["nursing", "procedures", q, department] as const,
  done: ["nursing", "procedures-done"] as const,
  visits: (q: string) => ["nursing", "visits", q] as const,
  chart: (visitId: number) => ["nursing", "chart", visitId] as const,
  board: ["nursing", "board"] as const,
  patients: (q: string) => ["nursing", "patients", q] as const,
  openVisits: (patientId: number) => ["nursing", "open-visits", patientId] as const,
  options: ["nursing", "visit-options"] as const,
};

/** Lines arrive as the cashier takes payments; the desk refreshes on its own. */
export const WORKLIST_REFRESH_MS = 15_000;
export const BOARD_REFRESH_MS = 30_000;

// --- procedures -------------------------------------------------------------------------------

export function useProcedureWorklist(q: string, department: number | null) {
  return useQuery({
    queryKey: nursingKeys.procedures(q, department),
    queryFn: () =>
      unwrap(
        api.GET("/api/orders/procedures", {
          params: { query: { q: q || undefined, department_id: department ?? undefined } },
        }),
      ),
    refetchInterval: WORKLIST_REFRESH_MS,
    placeholderData: keepPreviousData,
  });
}

export function useProceduresDone() {
  return useQuery({
    queryKey: nursingKeys.done,
    queryFn: () => unwrap(api.GET("/api/orders/procedures/done")),
    refetchInterval: WORKLIST_REFRESH_MS,
  });
}

export function useMarkDone() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ lineId, note }: { lineId: number; note: string }) =>
      unwrap(
        api.POST("/api/orders/procedures/{line_id}/done", {
          params: { path: { line_id: lineId } },
          body: { note },
        }),
      ),
    onSettled: () => qc.invalidateQueries({ queryKey: nursingKeys.all }),
  });
}

// --- visits, vitals, notes --------------------------------------------------------------------

export function useNursingVisits(q: string) {
  return useQuery({
    queryKey: nursingKeys.visits(q),
    queryFn: () => unwrap(api.GET("/api/clinical/nursing/visits", { params: { query: { q: q || undefined } } })),
    refetchInterval: WORKLIST_REFRESH_MS,
    placeholderData: keepPreviousData,
  });
}

export function useNursingChart(visitId: number) {
  return useQuery({
    queryKey: nursingKeys.chart(visitId),
    queryFn: () =>
      unwrap(api.GET("/api/clinical/nursing/visits/{visit_id}", { params: { path: { visit_id: visitId } } })),
  });
}

export function useRecordVitals(visitId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: VitalsInput) =>
      unwrap(api.POST("/api/clinical/visits/{visit_id}/vitals", { params: { path: { visit_id: visitId } }, body })),
    onSettled: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: nursingKeys.chart(visitId) }),
        qc.invalidateQueries({ queryKey: ["nursing", "visits"] }),
        // The doctor's workspace shows the same vitals.
        qc.invalidateQueries({ queryKey: ["clinic", "workspace", visitId] }),
      ]),
  });
}

export function useAddNursingNote(visitId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: NursingNoteInput) =>
      unwrap(
        api.POST("/api/clinical/nursing/visits/{visit_id}/notes", { params: { path: { visit_id: visitId } }, body }),
      ),
    onSettled: () => qc.invalidateQueries({ queryKey: nursingKeys.chart(visitId) }),
  });
}

// --- beds -------------------------------------------------------------------------------------

export function useBedBoard() {
  return useQuery({
    queryKey: nursingKeys.board,
    queryFn: () => unwrap(api.GET("/api/visits/inpatient/board")),
    refetchInterval: BOARD_REFRESH_MS,
  });
}

function useBoardMutation<TArgs, TResult>(fn: (args: TArgs) => Promise<TResult>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSettled: () => qc.invalidateQueries({ queryKey: nursingKeys.all }),
  });
}

export function useAdmit() {
  return useBoardMutation((body: AdmitInput) => unwrap(api.POST("/api/visits/inpatient/admissions", { body })));
}

export function useTransfer() {
  return useBoardMutation(({ admissionId, bedId }: { admissionId: number; bedId: number }) =>
    unwrap(
      api.POST("/api/visits/inpatient/admissions/{admission_id}/transfer", {
        params: { path: { admission_id: admissionId } },
        body: { bed_id: bedId },
      }),
    ),
  );
}

export function useDischarge() {
  return useBoardMutation(({ admissionId, summary }: { admissionId: number; summary: string }) =>
    unwrap(
      api.POST("/api/visits/inpatient/admissions/{admission_id}/discharge", {
        params: { path: { admission_id: admissionId } },
        body: { summary },
      }),
    ),
  );
}

export function useCancelAdmission() {
  return useBoardMutation(({ admissionId, body }: { admissionId: number; body: CancelAdmissionInput }) =>
    unwrap(
      api.POST("/api/visits/inpatient/admissions/{admission_id}/cancel", {
        params: { path: { admission_id: admissionId } },
        body,
      }),
    ),
  );
}

export function useSetBedStatus() {
  return useBoardMutation(({ bedId, status }: { bedId: number; status: "available" | "maintenance" }) =>
    unwrap(
      api.POST("/api/visits/inpatient/beds/{bed_id}/status", {
        params: { path: { bed_id: bedId } },
        body: { status },
      }),
    ),
  );
}

export function useChargeDue() {
  return useBoardMutation(() => unwrap(api.POST("/api/visits/inpatient/charge-due")));
}

// --- admit dialog lookups ---------------------------------------------------------------------

export function usePatientSearch(q: string) {
  return useQuery({
    queryKey: nursingKeys.patients(q),
    queryFn: () => unwrap(api.GET("/api/patients", { params: { query: { q, page: 1, page_size: 8 } } })),
    enabled: q.trim().length >= 2,
    placeholderData: keepPreviousData,
  });
}

export function useOpenVisits(patientId: number | null) {
  return useQuery({
    queryKey: nursingKeys.openVisits(patientId ?? 0),
    queryFn: () =>
      unwrap(
        api.GET("/api/visits", {
          params: { query: { patient_id: patientId ?? 0, status: "open", page: 1, page_size: 10 } },
        }),
      ),
    enabled: patientId !== null,
  });
}

export function useVisitOptions(enabled: boolean) {
  return useQuery({
    queryKey: nursingKeys.options,
    queryFn: () => unwrap(api.GET("/api/visits/options")),
    enabled,
    staleTime: 10 * 60_000,
  });
}
