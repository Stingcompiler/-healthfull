/**
 * Staff hooks for portal access codes from the patient's file at reception (ADR 0016
 * follow-up): list the file's codes (their state, never the codes), issue one for a printed
 * slip, revoke one. The rules are the server's.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";

export const portalCodeKeys = {
  patient: (patientId: number) => ["portal", "patient-codes", patientId] as const,
};

export function usePatientPortalCodes(patientId: number, enabled = true) {
  return useQuery({
    queryKey: portalCodeKeys.patient(patientId),
    queryFn: () =>
      unwrap(
        api.GET("/api/portal/patients/{patient_id}/access-codes", { params: { path: { patient_id: patientId } } }),
      ),
    enabled: enabled && patientId > 0,
  });
}

export function useIssuePatientPortalCode(patientId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/portal/patients/{patient_id}/access-codes", { params: { path: { patient_id: patientId } } }),
      ),
    onSettled: () => qc.invalidateQueries({ queryKey: portalCodeKeys.patient(patientId) }),
  });
}

export function useRevokePortalCode(patientId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ codeId, note }: { codeId: number; note: string }) =>
      unwrap(
        api.POST("/api/portal/access-codes/{code_id}/revoke", {
          params: { path: { code_id: codeId } },
          body: { note },
        }),
      ),
    onSettled: () => qc.invalidateQueries({ queryKey: portalCodeKeys.patient(patientId) }),
  });
}
