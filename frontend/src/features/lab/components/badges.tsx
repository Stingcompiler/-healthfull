import {
  ArrowDown,
  ArrowUp,
  CheckCheck,
  CircleDashed,
  ClipboardCheck,
  PencilLine,
  Syringe,
  Truck,
  TriangleAlert,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

import type { Flag, Stage } from "../types";

const STAGE_STYLES: Record<Stage, { icon: LucideIcon; className: string }> = {
  to_collect: { icon: Syringe, className: "bg-state-paid-bg text-state-paid-fg" },
  to_receive: { icon: Truck, className: "bg-info-bg text-info-fg" },
  to_enter: { icon: PencilLine, className: "bg-state-invoiced-bg text-state-invoiced-fg" },
  to_approve: { icon: ClipboardCheck, className: "bg-warning-bg text-warning-fg" },
  done: { icon: CheckCheck, className: "bg-state-performed-bg text-state-performed-fg" },
  cancelled: { icon: XCircle, className: "bg-state-cancelled-bg text-state-cancelled-fg" },
};

/** Where a test stands on the bench: icon and text, never color alone. */
export function StageBadge({ stage, className }: { stage: Stage; className?: string }) {
  const { t } = useTranslation("lab");
  const style = STAGE_STYLES[stage];
  const Icon = style.icon;
  return (
    <span
      data-slot="lab-stage"
      data-stage={stage}
      className={cn(
        "inline-flex w-fit shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-xs leading-4 font-medium whitespace-nowrap",
        style.className,
        className,
      )}
    >
      <Icon aria-hidden="true" className="size-3.5" />
      {t(`stage.${stage}`)}
    </span>
  );
}

function flagStyle(flag: Flag): { icon: LucideIcon | null; className: string } {
  if (flag === "critical_low" || flag === "critical_high")
    return { icon: TriangleAlert, className: "border-danger-border bg-danger-bg text-danger-fg" };
  if (flag === "high") return { icon: ArrowUp, className: "border-warning-border bg-warning-bg text-warning-fg" };
  if (flag === "low") return { icon: ArrowDown, className: "border-warning-border bg-warning-bg text-warning-fg" };
  if (flag === "abnormal")
    return { icon: TriangleAlert, className: "border-warning-border bg-warning-bg text-warning-fg" };
  if (flag === "normal") return { icon: null, className: "border-border text-fg-muted" };
  return { icon: CircleDashed, className: "border-border text-muted" };
}

/** A value's flag (high, low, critical...) with an icon and its name. */
export function FlagBadge({ flag, className }: { flag: Flag; className?: string }) {
  const { t } = useTranslation("lab");
  const style = flagStyle(flag);
  const Icon = style.icon;
  return (
    <span
      data-slot="lab-flag"
      data-flag={flag}
      className={cn(
        "inline-flex w-fit shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] leading-4 font-semibold whitespace-nowrap",
        style.className,
        className,
      )}
    >
      {Icon ? <Icon aria-hidden="true" className="size-3" /> : null}
      {t(`flag.${flag}`)}
    </span>
  );
}
