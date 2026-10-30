/** TanStack Query hooks over /api/visits (ARCHITECTURE 5.5). No business rules here. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";

import type {
  OnlineBookingStatus,
  AppointmentInput,
  AppointmentPatch,
  CheckInInput,
  QueueAction,
  VisitCancelInput,
  VisitInput,
} from "./types";

export const visitKeys = {
  all: ["visits"] as const,
  options: ["visits", "options"] as const,
  list: (query: VisitListQuery) => ["visits", "list", query] as const,
  detail: (id: number) => ["visits", "detail", id] as const,
  timeline: (id: number) => ["visits", "timeline", id] as const,
  board: (departmentId: number | null, includeFinished: boolean) =>
    ["visits", "board", departmentId, includeFinished] as const,
  display: (departmentId: number | null) => ["visits", "display", departmentId] as const,
  token: (entryId: number) => ["visits", "token", entryId] as const,
  agenda: (doctorId: number, day: string) => ["visits", "agenda", doctorId, day] as const,
  upcoming: (patientId: number) => ["visits", "upcoming", patientId] as const,
  online: (query: OnlineBookingQuery) => ["visits", "online", query] as const,
};

/** Filters of the reception inbox (ADR 0029 Phase 4); the server defaults to requests from today. */
export interface OnlineBookingQuery {
  status: OnlineBookingStatus;
  day: string | null;
  doctorId: number | null;
}

/** The inbox refreshes while reception keeps it open: requests arrive from the website. */
export const INBOX_REFRESH_MS = 30_000;

/** Board and display refresh: the queue changes as the cashier and doctors work. */
export const QUEUE_REFRESH_MS = 10_000;
export const DISPLAY_REFRESH_MS = 5_000;

export interface VisitListQuery {
  patientId?: number;
  day?: string;
  departmentId?: number;
  page?: number;
  pageSize?: number;
}

export function useVisitOptions() {
  return useQuery({
    queryKey: visitKeys.options,
    queryFn: () => unwrap(api.GET("/api/visits/options")),
    staleTime: 5 * 60_000,
  });
}

export function useVisitList(query: VisitListQuery, enabled = true) {
  return useQuery({
    queryKey: visitKeys.list(query),
    queryFn: () =>
      unwrap(
        api.GET("/api/visits", {
          params: {
            query: {
              patient_id: query.patientId,
              day: query.day,
              department_id: query.departmentId,
              page: query.page ?? 1,
              page_size: query.pageSize ?? 25,
            },
          },
        }),
      ),
    enabled,
  });
}

export function useVisitTimeline(id: number, enabled: boolean) {
  return useQuery({
    queryKey: visitKeys.timeline(id),
    queryFn: () => unwrap(api.GET("/api/visits/{visit_id}/timeline", { params: { path: { visit_id: id } } })),
    enabled,
  });
}

export function useBoard(departmentId: number | null, includeFinished: boolean) {
  return useQuery({
    queryKey: visitKeys.board(departmentId, includeFinished),
    queryFn: () =>
      unwrap(
        api.GET("/api/visits/queue/board", {
          params: { query: { department_id: departmentId ?? undefined, include_finished: includeFinished } },
        }),
      ),
    refetchInterval: QUEUE_REFRESH_MS,
  });
}

export function useWaitingRoom(departmentId: number | null) {
  return useQuery({
    queryKey: visitKeys.display(departmentId),
    queryFn: () =>
      unwrap(api.GET("/api/visits/queue/display", { params: { query: { department_id: departmentId ?? undefined } } })),
    refetchInterval: DISPLAY_REFRESH_MS,
    refetchIntervalInBackground: true,
  });
}

export function useTokenSlip(entryId: number | null) {
  return useQuery({
    queryKey: visitKeys.token(entryId ?? 0),
    queryFn: () =>
      unwrap(api.GET("/api/visits/queue/{entry_id}/token", { params: { path: { entry_id: entryId ?? 0 } } })),
    enabled: entryId !== null,
    staleTime: 0,
  });
}

export function useAgenda(doctorId: number | null, day: string) {
  return useQuery({
    queryKey: visitKeys.agenda(doctorId ?? 0, day),
    queryFn: () =>
      unwrap(api.GET("/api/visits/appointments/day", { params: { query: { doctor_id: doctorId ?? 0, day } } })),
    enabled: doctorId !== null,
  });
}

export function useUpcomingAppointments(patientId: number, enabled = true) {
  return useQuery({
    queryKey: visitKeys.upcoming(patientId),
    queryFn: () =>
      unwrap(api.GET("/api/visits/appointments/upcoming", { params: { query: { patient_id: patientId } } })),
    enabled,
  });
}

function useInvalidateVisits() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: visitKeys.all });
}

export function useCreateVisit() {
  const invalidate = useInvalidateVisits();
  return useMutation({
    mutationFn: (body: VisitInput) => unwrap(api.POST("/api/visits", { body })),
    onSuccess: invalidate,
  });
}

export function useCancelVisit() {
  const invalidate = useInvalidateVisits();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: VisitCancelInput }) =>
      unwrap(api.POST("/api/visits/{visit_id}/cancel", { params: { path: { visit_id: id } }, body })),
    // A paid visit's money becomes patient credit: the file's balance changes too.
    onSuccess: () => Promise.all([invalidate(), client.invalidateQueries({ queryKey: ["patients"] })]),
  });
}

export function useCallNext() {
  const invalidate = useInvalidateVisits();
  return useMutation({
    mutationFn: (departmentId: number) =>
      unwrap(api.POST("/api/visits/queue/call-next", { body: { department_id: departmentId } })),
    onSuccess: invalidate,
  });
}

export function useMoveQueueEntry() {
  const invalidate = useInvalidateVisits();
  return useMutation({
    mutationFn: ({ entryId, action }: { entryId: number; action: QueueAction }) =>
      unwrap(
        api.POST("/api/visits/queue/{entry_id}/move", { params: { path: { entry_id: entryId } }, body: { action } }),
      ),
    onSuccess: invalidate,
  });
}

export function useBookAppointment() {
  const invalidate = useInvalidateVisits();
  return useMutation({
    mutationFn: (body: AppointmentInput) => unwrap(api.POST("/api/visits/appointments", { body })),
    onSuccess: invalidate,
  });
}

export function useUpdateAppointment() {
  const invalidate = useInvalidateVisits();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: AppointmentPatch }) =>
      unwrap(
        api.PATCH("/api/visits/appointments/{appointment_id}", { params: { path: { appointment_id: id } }, body }),
      ),
    onSuccess: invalidate,
  });
}

export function useRescheduleAppointment() {
  const invalidate = useInvalidateVisits();
  return useMutation({
    mutationFn: ({ id, startsAt }: { id: number; startsAt: string }) =>
      unwrap(
        api.POST("/api/visits/appointments/{appointment_id}/reschedule", {
          params: { path: { appointment_id: id } },
          body: { starts_at: startsAt },
        }),
      ),
    onSuccess: invalidate,
  });
}

export function useCancelAppointment() {
  const invalidate = useInvalidateVisits();
  return useMutation({
    mutationFn: ({ id, reasonCode, note }: { id: number; reasonCode: string; note: string }) =>
      unwrap(
        api.POST("/api/visits/appointments/{appointment_id}/cancel", {
          params: { path: { appointment_id: id } },
          body: { reason_code: reasonCode, note },
        }),
      ),
    onSuccess: invalidate,
  });
}

/** Reception confirms an online request (ADR 0029 E; the inbox screen is Phase 4). */
export function useApproveOnlineBooking() {
  const invalidate = useInvalidateVisits();
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(
        api.POST("/api/visits/online-bookings/{appointment_id}/approve", {
          params: { path: { appointment_id: id } },
        }),
      ),
    onSuccess: invalidate,
  });
}

export function useRejectOnlineBooking() {
  const invalidate = useInvalidateVisits();
  return useMutation({
    mutationFn: ({ id, reasonCode, note }: { id: number; reasonCode: string; note: string }) =>
      unwrap(
        api.POST("/api/visits/online-bookings/{appointment_id}/reject", {
          params: { path: { appointment_id: id } },
          body: { reason_code: reasonCode, note },
        }),
      ),
    onSuccess: invalidate,
  });
}

export function useAppointmentNoShow() {
  const invalidate = useInvalidateVisits();
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(
        api.POST("/api/visits/appointments/{appointment_id}/no-show", { params: { path: { appointment_id: id } } }),
      ),
    onSuccess: invalidate,
  });
}

export function useCheckIn() {
  const invalidate = useInvalidateVisits();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: CheckInInput }) =>
      unwrap(
        api.POST("/api/visits/appointments/{appointment_id}/check-in", {
          params: { path: { appointment_id: id } },
          body,
        }),
      ),
    onSuccess: invalidate,
  });
}

// --- Reception inbox of online bookings (ADR 0029 D, F, G; apps/portal/inbox.py) ----------

export function useOnlineBookings(query: OnlineBookingQuery) {
  return useQuery({
    queryKey: visitKeys.online(query),
    queryFn: () =>
      unwrap(
        api.GET("/api/visits/online-bookings", {
          params: {
            query: {
              status: query.status,
              day: query.day ?? undefined,
              doctor_id: query.doctorId ?? undefined,
            },
          },
        }),
      ),
    refetchInterval: INBOX_REFRESH_MS,
  });
}

/** Cancel an online booking on the booker's behalf (reason code and note, invariant 4). */
export function useCancelOnlineBooking() {
  const invalidate = useInvalidateVisits();
  return useMutation({
    mutationFn: ({ id, reasonCode, note }: { id: number; reasonCode: string; note: string }) =>
      unwrap(
        api.POST("/api/visits/online-bookings/{appointment_id}/cancel", {
          params: { path: { appointment_id: id } },
          body: { reason_code: reasonCode, note },
        }),
      ),
    onSuccess: invalidate,
  });
}

/** Decline every open guest request of this booking's phone (one reason, one note). */
export function useRejectOnlineBookingsFromPhone() {
  const invalidate = useInvalidateVisits();
  return useMutation({
    mutationFn: ({ id, reasonCode, note }: { id: number; reasonCode: string; note: string }) =>
      unwrap(
        api.POST("/api/visits/online-bookings/{appointment_id}/reject-phone", {
          params: { path: { appointment_id: id } },
          body: { reason_code: reasonCode, note },
        }),
      ),
    onSuccess: invalidate,
  });
}

/** Link a booking made without a file to the patient's file (explicit; never automatic). */
export function useLinkOnlineBookingPatient() {
  const invalidate = useInvalidateVisits();
  return useMutation({
    mutationFn: ({ id, patientId }: { id: number; patientId: number }) =>
      unwrap(
        api.POST("/api/visits/online-bookings/{appointment_id}/link-patient", {
          params: { path: { appointment_id: id } },
          body: { patient_id: patientId },
        }),
      ),
    onSuccess: invalidate,
  });
}

/** A new PIN for a guest booking, shown once to the staff member (the old PIN stops working). */
export function useReissueGuestPin() {
  const invalidate = useInvalidateVisits();
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      unwrap(
        api.POST("/api/visits/online-bookings/{appointment_id}/reissue-pin", {
          params: { path: { appointment_id: id } },
          body: { reason },
        }),
      ),
    onSuccess: invalidate,
  });
}
