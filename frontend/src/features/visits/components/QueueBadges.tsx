import { CircleCheck, Clock3, Megaphone, Stethoscope, UserX, Wallet, XCircle, type LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";

import type { QueueStatus } from "../types";

const STYLE: Record<
  QueueStatus,
  { icon: LucideIcon; variant: "neutral" | "info" | "warning" | "success" | "danger" | "outline" }
> = {
  waiting: { icon: Clock3, variant: "neutral" },
  called: { icon: Megaphone, variant: "info" },
  in_progress: { icon: Stethoscope, variant: "warning" },
  done: { icon: CircleCheck, variant: "success" },
  no_show: { icon: UserX, variant: "danger" },
  cancelled: { icon: XCircle, variant: "outline" },
};

/** Queue state with an icon, so it is never told by color alone. */
export function QueueStatusBadge({ status }: { status: QueueStatus }) {
  const { t } = useTranslation("visits");
  const { icon: Icon, variant } = STYLE[status];
  return (
    <Badge variant={variant} data-status={status}>
      <Icon aria-hidden="true" />
      {t(`queueStatus.${status}`)}
    </Badge>
  );
}

/** Whether the consultation fee lets the doctor call the patient (paid, authorized or none due). */
export function FeeBadge({ ready }: { ready: boolean }) {
  const { t } = useTranslation("visits");
  return ready ? (
    <Badge variant="success">
      <CircleCheck aria-hidden="true" />
      {t("board.ready")}
    </Badge>
  ) : (
    <Badge variant="warning">
      <Wallet aria-hidden="true" />
      {t("board.awaitingPayment")}
    </Badge>
  );
}
