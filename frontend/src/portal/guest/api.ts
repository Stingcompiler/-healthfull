/**
 * Guest booking calls (ADR 0029 D, F; Phase 4a endpoints). No business rules: the server
 * checks the switches, caps, slot, proof-of-work and PIN. The guest cookie (`hospital_guest`,
 * path /api/portal/guest) is HttpOnly and never mixes with the patient or staff session.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { components } from "@/lib/api/schema";
import { api, unwrap } from "@/lib/api/client";
import { ensureCsrfToken } from "@/lib/api/csrf";

import type { AttemptDetails, AttemptProof } from "./attempt";

type S = components["schemas"];
export type GuestBookingCreated = S["GuestBookingCreatedOut"];
export type GuestBooking = S["GuestBookingOut"];
export type PortalDoctor = S["PortalDoctorOut"];
export type BookingDisplay = S["GuestBookingOut"]["display_status"];

export const guestKeys = {
  all: ["portal-guest"] as const,
  booking: ["portal-guest", "booking"] as const,
};

/** A guest signed in from this tab: only then is the booking asked for (no 401 noise). */
const SIGNED_IN_FLAG = "portal.guest.signedIn";

export function guestFlag(): boolean {
  try {
    return window.sessionStorage.getItem(SIGNED_IN_FLAG) === "1";
  } catch {
    return false;
  }
}

function setGuestFlag(on: boolean): void {
  try {
    if (on) window.sessionStorage.setItem(SIGNED_IN_FLAG, "1");
    else window.sessionStorage.removeItem(SIGNED_IN_FLAG);
  } catch {
    // storage blocked: the guest signs in again after a reload
  }
}

export async function fetchChallenge() {
  return unwrap(api.GET("/api/portal/challenge"));
}

/** The booking POST with the attempt's key in the `Idempotency-Key` header. */
export async function createGuestBooking(
  key: string,
  details: AttemptDetails,
  proof: AttemptProof,
): Promise<GuestBookingCreated> {
  await ensureCsrfToken();
  return unwrap(
    api.POST("/api/portal/guest-bookings", {
      params: { header: { "Idempotency-Key": key } },
      body: { ...details, ...proof },
    }),
  );
}

export function useGuestBooking(enabled: boolean) {
  return useQuery({
    queryKey: guestKeys.booking,
    queryFn: () => unwrap(api.GET("/api/portal/guest/booking")),
    enabled,
    retry: false,
    staleTime: 0,
  });
}

export function useGuestSignIn() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: { reference: string; pin: string }) => {
      await ensureCsrfToken();
      return unwrap(api.POST("/api/portal/guest-bookings/sign-in", { body }));
    },
    onSuccess: (booking) => {
      setGuestFlag(true);
      client.setQueryData(guestKeys.booking, booking);
    },
  });
}

export function useGuestSignOut() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/portal/guest/sign-out")),
    onSettled: () => {
      setGuestFlag(false);
      client.removeQueries({ queryKey: guestKeys.all });
    },
  });
}

/** The session ended on the server (idle, new PIN, switch off): forget the flag. */
export function forgetGuest(): void {
  setGuestFlag(false);
}

export function useGuestCancel() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/portal/guest/booking/cancel")),
    onSuccess: (booking) => client.setQueryData(guestKeys.booking, booking),
  });
}

export function useGuestReschedule() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { doctor_id: number; starts_at: string }) =>
      unwrap(api.POST("/api/portal/guest/booking/reschedule", { body })),
    onSuccess: (booking) => client.setQueryData(guestKeys.booking, booking),
  });
}
