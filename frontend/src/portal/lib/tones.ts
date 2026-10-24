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
