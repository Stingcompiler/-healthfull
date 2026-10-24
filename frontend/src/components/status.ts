import {
  BadgeCheck,
  Ban,
  CheckCheck,
  CircleDashed,
  Clock3,
  FileText,
  Wallet,
  XCircle,
  type LucideIcon,
} from "lucide-react";

/**
 * Service line states (ARCHITECTURE 4.4 derived state) and payment
 * verification states (4.6). Each pairs a color with an icon so the state is
 * never conveyed by color alone.
 */
export const SERVICE_LINE_STATES = ["requested", "invoiced", "paid", "performed", "cancelled"] as const;
export const VERIFICATION_STATES = ["pending_verification", "confirmed", "rejected"] as const;
export const STATUSES = [...SERVICE_LINE_STATES, ...VERIFICATION_STATES] as const;

export type ServiceLineState = (typeof SERVICE_LINE_STATES)[number];
export type VerificationState = (typeof VERIFICATION_STATES)[number];
export type Status = (typeof STATUSES)[number];

interface StatusStyle {
  icon: LucideIcon;
  className: string;
  dotClassName: string;
}

export const STATUS_STYLES: Record<Status, StatusStyle> = {
  requested: {
    icon: CircleDashed,
    className: "bg-state-requested-bg text-state-requested-fg",
    dotClassName: "bg-state-requested",
  },
  invoiced: {
    icon: FileText,
    className: "bg-state-invoiced-bg text-state-invoiced-fg",
    dotClassName: "bg-state-invoiced",
  },
  paid: { icon: Wallet, className: "bg-state-paid-bg text-state-paid-fg", dotClassName: "bg-state-paid" },
  performed: {
    icon: CheckCheck,
    className: "bg-state-performed-bg text-state-performed-fg",
    dotClassName: "bg-state-performed",
  },
  cancelled: {
    icon: XCircle,
    className: "bg-state-cancelled-bg text-state-cancelled-fg",
    dotClassName: "bg-state-cancelled",
  },
  // A transfer waits for a cashier to confirm it against the bank: staff must act, so this is
  // the amber "attention" role, not the neutral "pending" one (docs/DECISIONS.md D-0009).
  pending_verification: {
    icon: Clock3,
    className: "bg-state-attention-bg text-state-attention-fg",
    dotClassName: "bg-state-attention",
  },
  confirmed: { icon: BadgeCheck, className: "bg-success-bg text-success-fg", dotClassName: "bg-success" },
  rejected: { icon: Ban, className: "bg-danger-bg text-danger-fg", dotClassName: "bg-danger" },
};

export function isStatus(value: string): value is Status {
  return (STATUSES as readonly string[]).includes(value);
}
