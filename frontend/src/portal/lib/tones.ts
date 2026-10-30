/** Colour tone of a portal status label (semantic tokens only). */
export type PillTone = "success" | "warning" | "danger" | "info" | "neutral" | "pending";

export const PILL_CLASSES: Record<PillTone, string> = {
  success: "border-success-border bg-success-bg text-success-fg",
  warning: "border-warning-border bg-warning-bg text-warning-fg",
  danger: "border-danger-border bg-danger-bg text-danger-fg",
  info: "border-info-border bg-info-bg text-info-fg",
  neutral: "border-border bg-subtle text-fg",
  pending: "border-dashed border-state-pending-border bg-state-pending-bg text-state-pending-fg",
};

/**
 * Receipts: valid, a transfer the bank has not confirmed, or cancelled. For the patient an
 * unconfirmed transfer is only waiting (neutral "pending"): the staff who confirm it use the
 * amber attention state on the cashier screens.
 */
export const RECEIPT_TONE: Record<"valid" | "pending" | "void", PillTone> = {
  valid: "success",
  pending: "pending",
  void: "danger",
};

/** A booking's patient-facing status (server `display_status`, plan section 5) and its tone. */
export const BOOKING_TONE: Record<
  | "awaiting_approval"
  | "confirmed"
  | "received"
  | "moved"
  | "cancelled_by_you"
  | "cancelled_by_center"
  | "declined"
  | "expired"
  | "missed",
  PillTone
> = {
  awaiting_approval: "warning",
  confirmed: "info",
  received: "success",
  moved: "neutral",
  cancelled_by_you: "neutral",
  cancelled_by_center: "neutral",
  declined: "danger",
  expired: "neutral",
  missed: "warning",
};

/** A visit (plan section 5): at the center is happening now, completed is calm. */
export const VISIT_TONE: Record<"at_center" | "completed" | "cancelled", PillTone> = {
  at_center: "info",
  completed: "success",
  cancelled: "neutral",
};

/**
 * An order on the visit timeline. Amber only where the patient acts (pay at reception);
 * waiting for the department is neutral pending, never amber (D-0009).
 */
export const ORDER_TONE: Record<
  "pay_at_reception" | "waiting" | "in_progress" | "done" | "result_published" | "cancelled",
  PillTone
> = {
  pay_at_reception: "warning",
  waiting: "pending",
  in_progress: "info",
  done: "success",
  result_published: "success",
  cancelled: "neutral",
};

/** An approved invoice from the patient's side. */
export const PAYMENT_TONE: Record<"nothing_due" | "outstanding" | "under_verification" | "paid", PillTone> = {
  nothing_due: "neutral",
  outstanding: "warning",
  under_verification: "pending",
  paid: "success",
};
