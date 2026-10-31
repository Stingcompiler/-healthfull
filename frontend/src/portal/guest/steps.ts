/**
 * The booking steppers (D-0023, D-0024). Guest: doctor and time, your details, review,
 * confirmation. A signed-in patient (booking or moving a booking): doctor and time, then review;
 * the appointments list with its notice is the confirmation. Pure display state; the server
 * still checks every choice when the booking is sent.
 */
export const GUEST_STEPS = ["slot", "contact", "review", "done"] as const;

export type GuestStep = (typeof GUEST_STEPS)[number];

export const PATIENT_STEPS = ["slot", "review"] as const;

export type PatientStep = (typeof PATIENT_STEPS)[number];

export type StepState = "done" | "current" | "upcoming";

/** 1-based position of a step, for "Step 2 of 4". */
export function stepNumber<S extends string>(steps: readonly S[], step: S): number {
  return steps.indexOf(step) + 1;
}

/**
 * How a step reads while `current` is open. A final "done" step (the guest's confirmation)
 * counts as done once reached.
 */
export function stepState<S extends string>(steps: readonly S[], step: S, current: S): StepState {
  const at = steps.indexOf(step);
  const now = steps.indexOf(current);
  if (at < now || (current === "done" && step === "done")) return "done";
  return at === now ? "current" : "upcoming";
}

export interface SlotPick {
  doctorId: number | null;
  day: string | null;
  start: string | null;
}

/** Which parts of the slot step are shown: the day once a doctor is chosen, the time once a day is. */
export function revealed(pick: SlotPick): { day: boolean; time: boolean } {
  return { day: pick.doctorId !== null, time: pick.doctorId !== null && pick.day !== null };
}

/** The slot step is complete when a doctor and a free time are chosen. */
export function slotComplete(pick: SlotPick): boolean {
  return pick.doctorId !== null && pick.start !== null;
}
