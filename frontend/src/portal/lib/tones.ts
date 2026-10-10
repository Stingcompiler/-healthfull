/** Colour tone of a portal status label (semantic tokens only). */
export type PillTone = "success" | "warning" | "danger" | "info" | "neutral";

export const PILL_CLASSES: Record<PillTone, string> = {
  success: "border-success-border bg-success-bg text-success-fg",
  warning: "border-warning-border bg-warning-bg text-warning-fg",
  danger: "border-danger-border bg-danger-bg text-danger-fg",
  info: "border-info-border bg-info-bg text-info-fg",
  neutral: "border-border bg-subtle text-fg",
};

/** Receipts: valid, a transfer the bank has not confirmed, or cancelled. */
export const RECEIPT_TONE: Record<"valid" | "pending" | "void", PillTone> = {
  valid: "success",
  pending: "warning",
  void: "danger",
};
