/**
 * The guest booking stepper (D-0023): doctor and time, your details, review, confirmation.
 * Pure display state; the server still checks every choice when the booking is sent.
 */
export const GUEST_STEPS = ["slot", "contact", "review", "done"] as const;

export type GuestStep = (typeof GUEST_STEPS)[number];

export type StepState = "done" | "current" | "upcoming";

/** 1-based position of a step, for "Step 2 of 4". */
export function stepNumber(step: GuestStep): number {
  return GUEST_STEPS.indexOf(step) + 1;
}

/** How a step reads while `current` is open. The confirmation counts as done once reached. */
export function stepState(step: GuestStep, current: GuestStep): StepState {
  const at = GUEST_STEPS.indexOf(step);
  const now = GUEST_STEPS.indexOf(current);
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
