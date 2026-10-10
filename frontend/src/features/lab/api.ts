/**
 * TanStack Query hooks of the lab module (ARCHITECTURE 5.5). Every rule is the server's: these
 * hooks only fetch, send and refresh what the screens show.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";

import type {
  ApproverIn,
  LabParameterIn,
  LabParameterPatch,
  LabRangeIn,
  LabResult,
  LabTest,
  LabTestIn,
  LabTestPatch,
  WorklistFilter,
} from "./types";

export const labKeys = {
  all: ["lab"] as const,
  worklist: (status: WorklistFilter, q: string, page: number) => ["lab", "worklist", status, q, page] as const,
  result: (lineId: number) => ["lab", "result", lineId] as const,
  print: (lineId: number, versionId: number | undefined) => ["lab", "print", lineId, versionId ?? 0] as const,
  label: (sampleId: number) => ["lab", "label", sampleId] as const,
  approvals: (page: number) => ["lab", "approvals", page] as const,
  tests: ["lab", "tests"] as const,
  test: (testId: number) => ["lab", "test", testId] as const,
  services: ["lab", "services-available"] as const,
  tat: (from: string, to: string) => ["lab", "tat", from, to] as const,
  reasons: (category: string) => ["lab", "reasons", category] as const,
};

/** Page size of the lab lists. */
export const PAGE_SIZE = 25;

// --- reads ------------------------------------------------------------------------------------

export function useWorklist(status: WorklistFilter, q: string, page: number) {
  const term = q.trim();
  return useQuery({
    queryKey: labKeys.worklist(status, term, page),
    queryFn: () =>
      unwrap(
        api.GET("/api/lab/worklist", {
          params: { query: { status, q: term || null, page, page_size: PAGE_SIZE } },
        }),
      ),
    placeholderData: keepPreviousData,
    refetchInterval: 60_000,
  });
}

export function useLabResult(lineId: number) {
  return useQuery({
    queryKey: labKeys.result(lineId),
    queryFn: () => unwrap(api.GET("/api/lab/lines/{line_id}/result", { params: { path: { line_id: lineId } } })),
    staleTime: 0,
  });
}

export function useResultPrint(lineId: number, versionId: number | undefined) {
  return useQuery({
    queryKey: labKeys.print(lineId, versionId),
    queryFn: () =>
      unwrap(
        api.GET("/api/lab/lines/{line_id}/result/print", {
          params: { path: { line_id: lineId }, query: { version_id: versionId ?? null } },
        }),
      ),
  });
}

export function useSampleLabel(sampleId: number) {
  return useQuery({
    queryKey: labKeys.label(sampleId),
    queryFn: () => unwrap(api.GET("/api/lab/samples/{sample_id}/label", { params: { path: { sample_id: sampleId } } })),
  });
}

export function useApprovals(page: number) {
  return useQuery({
    queryKey: labKeys.approvals(page),
    queryFn: () => unwrap(api.GET("/api/lab/approvals", { params: { query: { page, page_size: PAGE_SIZE } } })),
    placeholderData: keepPreviousData,
    refetchInterval: 60_000,
  });
}

export function useLabTests() {
  return useQuery({ queryKey: labKeys.tests, queryFn: () => unwrap(api.GET("/api/lab/tests")) });
}

export function useLabTest(testId: number) {
  return useQuery({
    queryKey: labKeys.test(testId),
    queryFn: () => unwrap(api.GET("/api/lab/tests/{test_id}", { params: { path: { test_id: testId } } })),
  });
}

export function useUnlinkedServices(enabled: boolean) {
  return useQuery({
    queryKey: labKeys.services,
    queryFn: () => unwrap(api.GET("/api/lab/services-available")),
    enabled,
  });
}

export function useTurnaround(from: string, to: string) {
  return useQuery({
    queryKey: labKeys.tat(from, to),
    queryFn: () =>
      unwrap(
        api.GET("/api/lab/reports/turnaround", {
          params: { query: { date_from: from || null, date_to: to || null } },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

/** Active reasons of one list (sample rejection, amendment, cancellation). */
export function useLabReasons(category: "sample_reject" | "result_amend" | "line_cancel", enabled = true) {
  return useQuery({
    queryKey: labKeys.reasons(category),
    queryFn: () => unwrap(api.GET("/api/core/reason-codes", { params: { query: { category, active: true } } })),
    staleTime: 5 * 60_000,
    enabled,
  });
}

// --- bench commands ---------------------------------------------------------------------------

/** Every command answers with the test as the screen shows it next; lists refresh. */
function useResultMutation<V>(lineId: number, call: (vars: V) => Promise<LabResult>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSuccess: (data) => {
      qc.setQueryData(labKeys.result(lineId), data);
      void qc.invalidateQueries({ queryKey: ["lab", "worklist"] });
      void qc.invalidateQueries({ queryKey: ["lab", "approvals"] });
    },
  });
}

export function useCollectSample(lineId: number) {
  const qc = useQueryClient();
  return useResultMutation(lineId, async (vars: { lineIds: number[]; receive: boolean }) => {
    const data = await unwrap(
      api.POST("/api/lab/samples", { body: { line_ids: vars.lineIds, receive: vars.receive } }),
    );
    for (const id of vars.lineIds) if (id !== lineId) void qc.invalidateQueries({ queryKey: labKeys.result(id) });
    return data;
  });
}

export function useReceiveSample(lineId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sampleId: number) =>
      unwrap(api.POST("/api/lab/samples/{sample_id}/receive", { params: { path: { sample_id: sampleId } } })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: labKeys.result(lineId) });
      void qc.invalidateQueries({ queryKey: ["lab", "worklist"] });
    },
  });
}

export function useRejectSample(lineId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { sampleId: number; reason: string; note: string }) =>
      unwrap(
        api.POST("/api/lab/samples/{sample_id}/reject", {
          params: { path: { sample_id: vars.sampleId } },
          body: { reason: vars.reason, note: vars.note },
        }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["lab", "result"] });
      void qc.invalidateQueries({ queryKey: ["lab", "worklist"] });
      void qc.invalidateQueries({ queryKey: labKeys.result(lineId) });
    },
  });
}

export function useMarkLabelPrinted(sampleId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/lab/samples/{sample_id}/label-printed", { params: { path: { sample_id: sampleId } } })),
    onSuccess: (data) => {
      qc.setQueryData(labKeys.label(sampleId), data);
    },
  });
}

export function useEnterResults(lineId: number) {
  return useResultMutation(lineId, (vars: { values: Record<string, string>; comment?: string | null }) =>
    unwrap(
      api.PUT("/api/lab/lines/{line_id}/result", {
        params: { path: { line_id: lineId } },
        body: { values: vars.values, comment: vars.comment ?? null },
      }),
    ),
  );
}

export function useApproveResults(lineId: number) {
  return useResultMutation(lineId, (revision: string) =>
    unwrap(
      api.POST("/api/lab/lines/{line_id}/result/approve", {
        params: { path: { line_id: lineId } },
        body: { revision },
      }),
    ),
  );
}

export function useAmendResults(lineId: number) {
  return useResultMutation(lineId, (vars: { reason: string; note: string }) =>
    unwrap(
      api.POST("/api/lab/lines/{line_id}/result/amend", {
        params: { path: { line_id: lineId } },
        body: vars,
      }),
    ),
  );
}

export function useCancelTest(lineId: number) {
  return useResultMutation(lineId, (vars: { reason: string; note: string; approver: ApproverIn | null }) =>
    unwrap(
      api.POST("/api/lab/lines/{line_id}/cannot-perform", {
        params: { path: { line_id: lineId } },
        body: vars,
      }),
    ),
  );
}

// --- catalog ----------------------------------------------------------------------------------

function useTestMutation<V>(call: (vars: V) => Promise<LabTest>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSuccess: (data) => {
      qc.setQueryData(labKeys.test(data.id), data);
      void qc.invalidateQueries({ queryKey: labKeys.tests });
      void qc.invalidateQueries({ queryKey: labKeys.services });
    },
  });
}

export function useCreateTest() {
  return useTestMutation((body: LabTestIn) => unwrap(api.POST("/api/lab/tests", { body })));
}

export function useUpdateTest(testId: number) {
  return useTestMutation((body: LabTestPatch) =>
    unwrap(api.PATCH("/api/lab/tests/{test_id}", { params: { path: { test_id: testId } }, body })),
  );
}

export function useCreateParameter(testId: number) {
  return useTestMutation((body: LabParameterIn) =>
    unwrap(api.POST("/api/lab/tests/{test_id}/parameters", { params: { path: { test_id: testId } }, body })),
  );
}

export function useUpdateParameter() {
  return useTestMutation((vars: { parameterId: number; body: LabParameterPatch }) =>
    unwrap(
      api.PATCH("/api/lab/parameters/{parameter_id}", {
        params: { path: { parameter_id: vars.parameterId } },
        body: vars.body,
      }),
    ),
  );
}

export function useSaveRange() {
  return useTestMutation((vars: { parameterId: number; rangeId: number | null; body: LabRangeIn }) =>
    vars.rangeId === null
      ? unwrap(
          api.POST("/api/lab/parameters/{parameter_id}/ranges", {
            params: { path: { parameter_id: vars.parameterId } },
            body: vars.body,
          }),
        )
      : unwrap(
          api.PUT("/api/lab/ranges/{range_id}", { params: { path: { range_id: vars.rangeId } }, body: vars.body }),
        ),
  );
}

export function useDeleteRange() {
  return useTestMutation((rangeId: number) =>
    unwrap(api.DELETE("/api/lab/ranges/{range_id}", { params: { path: { range_id: rangeId } } })),
  );
}
